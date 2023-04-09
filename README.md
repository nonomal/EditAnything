# Edit Anything by Segment Anything

This is an ongoing project aims to **Edit and Generate Anything** in an image,
powered by [Segment Anything](https://github.com/facebookresearch/segment-anything), [ControlNet](https://github.com/lllyasviel/ControlNet),
[BLIP2](https://github.com/salesforce/LAVIS/tree/main/projects/blip2), [Stable Diffusion](https://huggingface.co/spaces/stabilityai/stable-diffusion), etc.

This is a small project for fun. Any forms of contribution and suggestion
are very welcomed!



# News

2023/04/09 - We released a pretrained model of StableDiffusion based ControlNet that generate images conditioned by SAM segmentation.

# Features

Highlight features:
- Pretrained ControlNet with SAM mask as condition enables the image generation with fine-grained control.
- BLIP2 text generation enables text guidance-free control.


## Generation Anything by Segment Anything

BLIP2 Prompt: "a large white and red ferry"
![p](images/sample1.jpg)
(1:input image; 2: segmentation mask; 3-8: generated images.)

BLIP2 Prompt: "a cloudy sky"
![p](images/sample2.jpg)

BLIP2 Prompt: "a black drone flying in the blue sky"
![p](images/sample3.jpg)


1) The human prompt and BLIP2 generated prompt build the text instruction.
2) The SAM model segment the input image to generate segmentation mask without category.
3) The segmentation mask and text instruction guide the image generation.


# Ongoing

- [x] Conditional Generation trained with 85k samples in SM dataset.

- [ ] Training with more images from LAION and SM.

- [ ] Interactive control on different masks for image editing.

- [ ] Using [Grounding DINO](https://github.com/IDEA-Research/Grounded-Segment-Anything) for category-related auto editing. 

- [ ] ChatGPT guided image editing.



# Setup

**Create a environment**

```bash
    conda env create -f environment.yaml
    conda activate control
```

**Install BLIP2 and SAM**

Put these models in `models` folder.
```bash
pip install git+https://github.com/huggingface/transformers.git

pip install git+https://github.com/facebookresearch/segment-anything.git
```

**Download pretrained model**
```bash

# Segment-anything ViT-H SAM model. 
cd models/
wget https://dl.fbaipublicfiles.com/segment_anything/sam_vit_h_4b8939.pth

# BLIP2 model will be auto downloaded.

# Get edit-anything-ckpt-v0-1.ckpt pretrained model from huggingface.
https://huggingface.co/shgao/edit-anything-v0-1

```


**Run Demo**
```
python sam2image.py
```
Set 'use_gradio = True' in sam2image.py if you
have GUI to run the gradio demo.


# Training

1. Generate training dataset with `dataset_build.py`.
2. Transfer stable-diffusion model with `tool_add_control_sd21.py`.
2. Train model with `tool_add_control_sd21.py`.


# Acknowledgement
This project is based on:

[Segment Anything](https://github.com/facebookresearch/segment-anything),
[ControlNet](https://github.com/lllyasviel/ControlNet),
[BLIP2](https://github.com/salesforce/LAVIS/tree/main/projects/blip2),
[MDT](https://github.com/sail-sg/MDT),
[Stable Diffusion](https://huggingface.co/spaces/stabilityai/stable-diffusion),
[Large-scale Unsupervised Semantic Segmentation](https://github.com/LUSSeg)

Thanks for these amazing project!
