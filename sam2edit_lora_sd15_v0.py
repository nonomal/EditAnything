# Edit Anything trained with Stable Diffusion + ControlNet + SAM  + BLIP2
from torchvision.utils import save_image
from PIL import Image
from pytorch_lightning import seed_everything
import subprocess
from collections import OrderedDict
import re
import cv2
import einops
import gradio as gr
import numpy as np
import torch
import random
import os
import requests
from io import BytesIO
from annotator.util import resize_image, HWC3

import torch
from safetensors.torch import load_file
from collections import defaultdict
from diffusers import StableDiffusionControlNetPipeline

def get_pipeline_embeds(pipeline, prompt, negative_prompt, device):
    # https://github.com/huggingface/diffusers/issues/2136
    """ Get pipeline embeds for prompts bigger than the maxlength of the pipe
    :param pipeline:
    :param prompt:
    :param negative_prompt:
    :param device:
    :return:
    """
    max_length = pipeline.tokenizer.model_max_length

    # simple way to determine length of tokens
    count_prompt = len(re.split(r', ', prompt))
    count_negative_prompt = len(re.split(r', ', negative_prompt))
    # count_prompt = len(prompt.split(","))
    # count_negative_prompt = len(negative_prompt.split(","))

    # create the tensor based on which prompt is longer
    if count_prompt >= count_negative_prompt:
        input_ids = pipeline.tokenizer(prompt, return_tensors="pt", truncation=False).input_ids.to(device)
        shape_max_length = input_ids.shape[-1]
        negative_ids = pipeline.tokenizer(negative_prompt, truncation=False, padding="max_length",
                                          max_length=shape_max_length, return_tensors="pt").input_ids.to(device)

    else:
        negative_ids = pipeline.tokenizer(negative_prompt, return_tensors="pt", truncation=False).input_ids.to(device)
        shape_max_length = negative_ids.shape[-1]
        input_ids = pipeline.tokenizer(prompt, return_tensors="pt", truncation=False, padding="max_length",
                                       max_length=shape_max_length).input_ids.to(device)

    concat_embeds = []
    neg_embeds = []
    for i in range(0, shape_max_length, max_length):
        concat_embeds.append(pipeline.text_encoder(input_ids[:, i: i + max_length])[0])
        neg_embeds.append(pipeline.text_encoder(negative_ids[:, i: i + max_length])[0])

    return torch.cat(concat_embeds, dim=1), torch.cat(neg_embeds, dim=1)

def load_lora_weights(pipeline, checkpoint_path, multiplier, device, dtype):
    LORA_PREFIX_UNET = "lora_unet"
    LORA_PREFIX_TEXT_ENCODER = "lora_te"
    # load LoRA weight from .safetensors
    if isinstance(checkpoint_path, str):

        state_dict = load_file(checkpoint_path, device=device)

        updates = defaultdict(dict)
        for key, value in state_dict.items():
            # it is suggested to print out the key, it usually will be something like below
            # "lora_te_text_model_encoder_layers_0_self_attn_k_proj.lora_down.weight"

            layer, elem = key.split('.', 1)
            updates[layer][elem] = value

        # directly update weight in diffusers model
        for layer, elems in updates.items():

            if "text" in layer:
                layer_infos = layer.split(LORA_PREFIX_TEXT_ENCODER + "_")[-1].split("_")
                curr_layer = pipeline.text_encoder
            else:
                layer_infos = layer.split(LORA_PREFIX_UNET + "_")[-1].split("_")
                curr_layer = pipeline.unet

            # find the target layer
            temp_name = layer_infos.pop(0)
            while len(layer_infos) > -1:
                try:
                    curr_layer = curr_layer.__getattr__(temp_name)
                    if len(layer_infos) > 0:
                        temp_name = layer_infos.pop(0)
                    elif len(layer_infos) == 0:
                        break
                except Exception:
                    if len(temp_name) > 0:
                        temp_name += "_" + layer_infos.pop(0)
                    else:
                        temp_name = layer_infos.pop(0)

            # get elements for this layer
            weight_up = elems['lora_up.weight'].to(dtype)
            weight_down = elems['lora_down.weight'].to(dtype)
            alpha = elems['alpha']
            if alpha:
                alpha = alpha.item() / weight_up.shape[1]
            else:
                alpha = 1.0

            # update weight
            if len(weight_up.shape) == 4:
                curr_layer.weight.data += multiplier * alpha * torch.mm(weight_up.squeeze(3).squeeze(2), weight_down.squeeze(3).squeeze(2)).unsqueeze(2).unsqueeze(3)
            else:
                curr_layer.weight.data += multiplier * alpha * torch.mm(weight_up, weight_down)
    else:
        for ckptpath in checkpoint_path:
            state_dict = load_file(ckptpath, device=device)

            updates = defaultdict(dict)
            for key, value in state_dict.items():
                # it is suggested to print out the key, it usually will be something like below
                # "lora_te_text_model_encoder_layers_0_self_attn_k_proj.lora_down.weight"

                layer, elem = key.split('.', 1)
                updates[layer][elem] = value

            # directly update weight in diffusers model
            for layer, elems in updates.items():
                print(layer)
                if "text" in layer:
                    layer_infos = layer.split(LORA_PREFIX_TEXT_ENCODER + "_")[-1].split("_")
                    curr_layer = pipeline.text_encoder
                else:
                    layer_infos = layer.split(LORA_PREFIX_UNET + "_")[-1].split("_")
                    curr_layer = pipeline.unet

                # find the target layer
                temp_name = layer_infos.pop(0)
                while len(layer_infos) > -1:
                    try:
                        curr_layer = curr_layer.__getattr__(temp_name)
                        if len(layer_infos) > 0:
                            temp_name = layer_infos.pop(0)
                        elif len(layer_infos) == 0:
                            break
                    except Exception:
                        if len(temp_name) > 0:
                            temp_name += "_" + layer_infos.pop(0)
                        else:
                            temp_name = layer_infos.pop(0)

                # get elements for this layer
                weight_up = elems['lora_up.weight'].to(dtype)
                weight_down = elems['lora_down.weight'].to(dtype)
                alpha = elems['alpha']
                if alpha:
                    alpha = alpha.item() / weight_up.shape[1]
                else:
                    alpha = 1.0

                # update weight
                print(curr_layer.weight.data.shape, weight_up.shape, weight_down.shape)
                if len(weight_up.shape) == 4:
                    curr_layer.weight.data += multiplier * alpha * torch.mm(weight_up.squeeze(3).squeeze(2), weight_down.squeeze(3).squeeze(2)).unsqueeze(2).unsqueeze(3)
                else:
                    curr_layer.weight.data += multiplier * alpha * torch.mm(weight_up, weight_down)
    return pipeline

def create_demo():
    device = "cuda" if torch.cuda.is_available() else "cpu"
    use_blip = True
    use_gradio = True

    # Diffusion init using diffusers.

    # diffusers==0.14.0 required.
    from diffusers import StableDiffusionInpaintPipeline
    from diffusers import ControlNetModel, UniPCMultistepScheduler
    from utils.stable_diffusion_controlnet_inpaint import StableDiffusionControlNetInpaintPipeline
    from diffusers.utils import load_image

    # base_model_path = "runwayml/stable-diffusion-inpainting"
    base_model_path = "../chilloutmix_NiPrunedFp32Fix"
    lora_model_path = "../40806/mix4"

    config_dict = OrderedDict([('SAM Pretrained(v0-1): Good Natural Sense', 'shgao/edit-anything-v0-1-1'),
                            ('LAION Pretrained(v0-3): Good Face', '../../edit/laion-sd15'),
                            ('SD Inpainting: Not keep position', 'runwayml/stable-diffusion-inpainting'),
                            ('Geneation only for SD15', '../../edit/laion-sd15')
                            ])
    def obtain_generation_model(controlnet_path, generation_only=True):
        if generation_only:
            controlnet = ControlNetModel.from_pretrained(controlnet_path, torch_dtype=torch.float16)
            pipe = StableDiffusionControlNetPipeline.from_pretrained(
                base_model_path, controlnet=controlnet, torch_dtype=torch.float16
            )
        elif controlnet_path=='runwayml/stable-diffusion-inpainting':
            pipe = StableDiffusionInpaintPipeline.from_pretrained(
                "runwayml/stable-diffusion-inpainting",
                torch_dtype=torch.float16,
            )
        else:
            controlnet = ControlNetModel.from_pretrained(controlnet_path, torch_dtype=torch.float16)
            pipe = StableDiffusionControlNetInpaintPipeline.from_pretrained(
                base_model_path, controlnet=controlnet, torch_dtype=torch.float16
            )
        pipe=load_lora_weights(pipe, [lora_model_path],1.0,'cpu',torch.float32)
        #pipe.unet.load_attn_procs(lora_model_path)
        # pipe.load_lora_weights(lora_model_path) #incoming new diffusers version
        # speed up diffusion process with faster scheduler and memory optimization
        pipe.scheduler = UniPCMultistepScheduler.from_config(pipe.scheduler.config)
        # remove following line if xformers is not installed
        pipe.enable_xformers_memory_efficient_attention()

        pipe.enable_model_cpu_offload() # disable for now because of unknow bug in accelerate
        # pipe.to(device)
        return pipe
    global default_controlnet_path
    global pipe
    default_controlnet_path = config_dict['Geneation only for SD15']
    # default_controlnet_path = config_dict['SD Inpainting: Not keep position']
    
    pipe = obtain_generation_model(default_controlnet_path)

    # Segment-Anything init.
    # pip install git+https://github.com/facebookresearch/segment-anything.git

    try:
        from segment_anything import sam_model_registry, SamAutomaticMaskGenerator
    except ImportError:
        print('segment_anything not installed')
        result = subprocess.run(['pip', 'install', 'git+https://github.com/facebookresearch/segment-anything.git'], check=True)
        print(f'Install segment_anything {result}')   
        from segment_anything import sam_model_registry, SamAutomaticMaskGenerator
    if not os.path.exists('./models/sam_vit_h_4b8939.pth'):
        result = subprocess.run(['wget', 'https://dl.fbaipublicfiles.com/segment_anything/sam_vit_h_4b8939.pth', '-P', 'models'], check=True)
        print(f'Download sam_vit_h_4b8939.pth {result}')   
    sam_checkpoint = "models/sam_vit_h_4b8939.pth"
    model_type = "default"
    sam = sam_model_registry[model_type](checkpoint=sam_checkpoint)
    sam.to(device=device)
    mask_generator = SamAutomaticMaskGenerator(sam)


    # BLIP2 init.
    if use_blip:
        # need the latest transformers
        # pip install git+https://github.com/huggingface/transformers.git
        from transformers import AutoProcessor, Blip2ForConditionalGeneration

        processor = AutoProcessor.from_pretrained("Salesforce/blip2-opt-2.7b")
        blip_model = Blip2ForConditionalGeneration.from_pretrained(
            "Salesforce/blip2-opt-2.7b", torch_dtype=torch.float16, device_map="auto")


    def get_blip2_text(image):
        inputs = processor(image, return_tensors="pt").to(device, torch.float16)
        generated_ids = blip_model.generate(**inputs, max_new_tokens=50)
        generated_text = processor.batch_decode(
            generated_ids, skip_special_tokens=True)[0].strip()
        return generated_text


    def show_anns(anns):
        if len(anns) == 0:
            return
        sorted_anns = sorted(anns, key=(lambda x: x['area']), reverse=True)
        full_img = None

        # for ann in sorted_anns:
        for i in range(len(sorted_anns)):
            ann = anns[i]
            m = ann['segmentation']
            if full_img is None:
                full_img = np.zeros((m.shape[0], m.shape[1], 3))
                map = np.zeros((m.shape[0], m.shape[1]), dtype=np.uint16)
            map[m != 0] = i + 1
            color_mask = np.random.random((1, 3)).tolist()[0]
            full_img[m != 0] = color_mask
        full_img = full_img*255
        # anno encoding from https://github.com/LUSSeg/ImageNet-S
        res = np.zeros((map.shape[0], map.shape[1], 3))
        res[:, :, 0] = map % 256
        res[:, :, 1] = map // 256
        res.astype(np.float32)
        full_img = Image.fromarray(np.uint8(full_img))
        return full_img, res


    def get_sam_control(image):
        masks = mask_generator.generate(image)
        full_img, res = show_anns(masks)
        return full_img, res


    def process(condition_model, source_image, enable_all_generate, mask_image, control_scale, enable_auto_prompt, prompt, a_prompt, n_prompt, num_samples, image_resolution, detect_resolution, ddim_steps, guess_mode, strength, scale, seed, eta):

        input_image = source_image["image"]
        if mask_image is None:
            if enable_all_generate:
                print("source_image", source_image["mask"].shape, input_image.shape,)
                print(source_image["mask"].max())
                mask_image = np.ones((input_image.shape[0], input_image.shape[1], 3))*255
            else:
                mask_image = source_image["mask"]
        global default_controlnet_path
        print("To Use:", config_dict[condition_model], "Current:", default_controlnet_path)
        if default_controlnet_path!=config_dict[condition_model]:
            print("Change condition model to:", config_dict[condition_model])
            global pipe
            pipe = obtain_generation_model(config_dict[condition_model])
            default_controlnet_path = config_dict[condition_model]
            torch.cuda.empty_cache()

        with torch.no_grad():
            if use_blip and (enable_auto_prompt or len(prompt) == 0):
                print("Generating text:")
                blip2_prompt = get_blip2_text(input_image)
                print("Generated text:", blip2_prompt)
                if len(prompt)>0:
                    prompt = blip2_prompt + ',' + prompt
                else:
                    prompt = blip2_prompt
                print("All text:", prompt)

            input_image = HWC3(input_image)

            img = resize_image(input_image, image_resolution)
            H, W, C = img.shape

            print("Generating SAM seg:")
            # the default SAM model is trained with 1024 size.
            full_segmask, detected_map = get_sam_control(
                resize_image(input_image, detect_resolution))

            detected_map = HWC3(detected_map.astype(np.uint8))
            detected_map = cv2.resize(
                detected_map, (W, H), interpolation=cv2.INTER_LINEAR)

            control = torch.from_numpy(
                detected_map.copy()).float().cuda()
            control = torch.stack([control for _ in range(num_samples)], dim=0)
            control = einops.rearrange(control, 'b h w c -> b c h w').clone()

            mask_image = HWC3(mask_image.astype(np.uint8))
            mask_image = cv2.resize(
                mask_image, (W, H), interpolation=cv2.INTER_LINEAR)
            mask_image = Image.fromarray(mask_image)


            if seed == -1:
                seed = random.randint(0, 65535)
            seed_everything(seed)
            generator = torch.manual_seed(seed)
            # postive_prompt=[prompt + ', ' + a_prompt] * num_samples
            # negative_prompt=[n_prompt] * num_samples
            postive_prompt=prompt + ', ' + a_prompt
            negative_prompt=n_prompt
            prompt_embeds, negative_prompt_embeds = get_pipeline_embeds(pipe, postive_prompt, negative_prompt, "cuda")
            print(prompt_embeds.shape)
            prompt_embeds=torch.cat([prompt_embeds] * num_samples, dim=0)
            negative_prompt_embeds=torch.cat([negative_prompt_embeds] * num_samples, dim=0)
            if condition_model=='SD Inpainting: Not keep position':
                x_samples = pipe(
                    image=img,
                    mask_image=mask_image,
                    prompt_embeds=prompt_embeds, negative_prompt_embeds=negative_prompt_embeds,
                    # prompt=[prompt + ', ' + a_prompt] * num_samples,
                    # negative_prompt=[n_prompt] * num_samples,  
                    num_images_per_prompt=num_samples,
                    num_inference_steps=ddim_steps, 
                    generator=generator, 
                    height=H,
                    width=W,
                ).images
            elif condition_model=='Geneation only for SD15':
                pipe.safety_checker = lambda images, clip_input: (images, False)
                print(type(control))
                x_samples = pipe(
                    prompt_embeds=prompt_embeds, negative_prompt_embeds=negative_prompt_embeds,
                    # prompt=[prompt + ', ' + a_prompt] * num_samples,
                    # negative_prompt=[n_prompt] * num_samples,
                    num_images_per_prompt=num_samples,
                    num_inference_steps=ddim_steps,
                    generator=generator,
                    height=H,
                    width=W,
                    image=control.type(torch.float16),
                    controlnet_conditioning_scale=float(control_scale),
                ).images
            else:
                x_samples = pipe(
                    image=img,
                    mask_image=mask_image,
                    prompt_embeds=prompt_embeds, negative_prompt_embeds=negative_prompt_embeds,
                    # prompt=[prompt + ', ' + a_prompt] * num_samples,
                    # negative_prompt=[n_prompt] * num_samples,  
                    num_images_per_prompt=num_samples,
                    num_inference_steps=ddim_steps, 
                    generator=generator, 
                    controlnet_conditioning_image=control.type(torch.float16),
                    height=H,
                    width=W,
                    controlnet_conditioning_scale=control_scale,
                ).images


            results = [x_samples[i] for i in range(num_samples)]
        return [full_segmask, mask_image] + results, prompt


    def download_image(url):
        response = requests.get(url)
        return Image.open(BytesIO(response.content)).convert("RGB")

    # disable gradio when not using GUI.
    if not use_gradio:
        # This part is not updated, it's just a example to use it without GUI.
        image_path = "../data/samples/sa_223750.jpg"
        mask_path = "../data/samples/sa_223750inpaint.png"
        input_image = Image.open(image_path)
        mask_image = Image.open(mask_path)
        enable_auto_prompt = True
        input_image = np.array(input_image, dtype=np.uint8)
        mask_image = np.array(mask_image, dtype=np.uint8)
        prompt = "esplendent sunset sky, red brick wall"
        a_prompt = 'best quality, extremely detailed'
        n_prompt = 'longbody, lowres, bad anatomy, bad hands, missing fingers, extra digit, fewer digits, cropped, worst quality, low quality'
        num_samples = 3
        image_resolution = 512
        detect_resolution = 512
        ddim_steps = 30
        guess_mode = False
        strength = 1.0
        scale = 9.0
        seed = -1
        eta = 0.0

        outputs = process(condition_model, input_image, mask_image, enable_auto_prompt, prompt, a_prompt, n_prompt, num_samples, image_resolution,
                        detect_resolution, ddim_steps, guess_mode, strength, scale, seed, eta)

        image_list = []
        input_image = resize_image(input_image, 512)
        image_list.append(torch.tensor(input_image))
        for i in range(len(outputs)):
            each = outputs[i]
            if type(each) is not np.ndarray:
                each = np.array(each, dtype=np.uint8)
            each = resize_image(each, 512)
            print(i, each.shape)
            image_list.append(torch.tensor(each))

        image_list = torch.stack(image_list).permute(0, 3, 1, 2)

        save_image(image_list, "sample.jpg", nrow=3,
                normalize=True, value_range=(0, 255))
    else:
        print("The GUI is not fully tested yet. Please open an issue if you find bugs.")
        block = gr.Blocks()
        with block as demo:
            with gr.Row():
                gr.Markdown(
                    "## Edit Anything")
            with gr.Row():
                with gr.Column():
                    source_image = gr.Image(source='upload',label="Image (Upload an image and cover the region you want to edit with sketch)",  type="numpy", tool="sketch")
                    enable_all_generate = gr.Checkbox(label='Auto generation on all region.', value=False)
                    prompt = gr.Textbox(label="Prompt (Text in the expected things of edited region)")
                    enable_auto_prompt = gr.Checkbox(label='Auto generate text prompt from input image with BLIP2: Warning: Enable this may makes your prompt not working.', value=True)
                    control_scale = gr.Slider(
                            label="Mask Align strength (Large value means more strict alignment with SAM mask)", minimum=0, maximum=1, value=1, step=0.1)
                    run_button = gr.Button(label="Run")
                    condition_model = gr.Dropdown(choices=list(config_dict.keys()),
                                                value=list(config_dict.keys())[1],
                                                label='Model',
                                                multiselect=False)
                    num_samples = gr.Slider(
                            label="Images", minimum=1, maximum=12, value=2, step=1)
                    a_prompt = gr.Textbox(
                        label="Added Prompt", value='best quality, extremely detailed')
                    n_prompt = gr.Textbox(label="Negative Prompt",
                                        value='longbody, lowres, bad anatomy, bad hands, missing fingers, extra digit, fewer digits, cropped, worst quality, low quality')
                    with gr.Accordion("Advanced options", open=False):
                        mask_image = gr.Image(source='upload', label="(Optional) Upload a predefined mask of edit region if you do not want to write your prompt.", type="numpy", value=None)
                        image_resolution = gr.Slider(
                            label="Image Resolution", minimum=256, maximum=768, value=512, step=64)
                        strength = gr.Slider(
                            label="Control Strength", minimum=0.0, maximum=2.0, value=1.0, step=0.01)
                        guess_mode = gr.Checkbox(label='Guess Mode', value=False)
                        detect_resolution = gr.Slider(
                            label="SAM Resolution", minimum=128, maximum=2048, value=1024, step=1)
                        ddim_steps = gr.Slider(
                            label="Steps", minimum=1, maximum=100, value=30, step=1)
                        scale = gr.Slider(
                            label="Guidance Scale", minimum=0.1, maximum=30.0, value=9.0, step=0.1)
                        seed = gr.Slider(label="Seed", minimum=-1,
                                        maximum=2147483647, step=1, randomize=True)
                        eta = gr.Number(label="eta (DDIM)", value=0.0)
                with gr.Column():
                    result_gallery = gr.Gallery(
                        label='Output', show_label=False, elem_id="gallery").style(grid=2, height='auto')
                    result_text = gr.Text(label='BLIP2+Human Prompt Text')
            ips = [condition_model, source_image, enable_all_generate, mask_image, control_scale, enable_auto_prompt, prompt, a_prompt, n_prompt, num_samples, image_resolution,
                detect_resolution, ddim_steps, guess_mode, strength, scale, seed, eta]
            run_button.click(fn=process, inputs=ips, outputs=[result_gallery, result_text])
        return demo

if __name__ == '__main__':
    demo = create_demo()
    demo.queue().launch(server_name='0.0.0.0')
