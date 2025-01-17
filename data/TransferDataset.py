import os
import torch
import torch.utils.data
import numpy as np
import torchvision.transforms as transforms
from PIL import Image
import random
import matplotlib.pyplot as plt
import cv2

class TransferDataset(torch.utils.data.Dataset):
    def __init__(self, opt):
        super(TransferDataset, self).__init__()
        self.opt = opt
        if self.opt.isTrain:
            ## [10 and 5]
            self.rate = 5
            self.dir_inpainting = '/home/fiftywu/fiftywu/Files/DeepLearning/Cityscape_Inpainting/dataset/train'
            self.inpainting_paths = sorted([os.path.join(self.dir_inpainting, name) for name in os.listdir(self.dir_inpainting)])

            self.rand_dir_inpainting = '/home/fiftywu/fiftywu/Files/DeepLearning/Cityscape_Inpainting/dataset/rand'
            self.rand_inpainting_paths = sorted([os.path.join(self.rand_dir_inpainting, name) for name in os.listdir(self.rand_dir_inpainting)])

            self.dir_synthesis = '/home/fiftywu/fiftywu/Files/DeepLearning/EmptycitiesCarla/ABC/train'
            self.synthesis_paths = sorted([os.path.join(self.dir_synthesis, name) for name in os.listdir(self.dir_synthesis)])
        else:
            self.dir_inpainting = '/home/fiftywu/fiftywu/Files/DeepLearning/Carla_Transfer/Cityscape/val'
            self.inpainting_paths = sorted([os.path.join(self.dir_inpainting, name) for name in os.listdir(self.dir_inpainting)])

    def __getitem__(self, index):
        ##------realistic------##
        raw_AC_path = self.inpainting_paths[index]
        raw_AC = Image.open(raw_AC_path)  # PIL 0,255
        w, h = raw_AC.size
        w2 = w//2
        raw_A = raw_AC.crop((0, 0, w2, h))
        raw_C = raw_AC.crop((w2, 0, w, h))
        transform_paras = get_params(self.opt, raw_A.size)
        real_transform = get_transform(self.opt, transform_paras, grayscale=True)
        raw_A = real_transform(raw_A)
        raw_C = (real_transform(raw_C) + 1) * 0.5  # 0 - 1
        if not self.opt.isTrain:
            real_data = [{
                'inpaint_A': raw_A,
                'inpaint_B': raw_A,
                'inpaint_C': raw_C,
                'inpaint_name': raw_AC_path.split('/')[-1].replace('.png', '')
            }]
            return real_data, [{}]

        if self.opt.isTrain:
            ##------realistic------##
            # random dynamic and its mask
            random_index =  random.randint(0, len(self.rand_inpainting_paths)-1)
            rand_AC_path = self.rand_inpainting_paths[random_index]
            rand_AC = Image.open(rand_AC_path)
            w, h = rand_AC.size
            w2 = w//2
            rand_A = rand_AC.crop((0, 0, w2, h))
            rand_C = rand_AC.crop((w2, 0, w, h))
            transform_paras = get_params(self.opt, rand_A.size)
            real_transform = get_transform(self.opt, transform_paras, grayscale=True)
            rand_A = real_transform(rand_A)
            rand_C = (real_transform(rand_C) + 1) * 0.5 # 0 - 1

            ## >>
            inpaint_A = raw_A * (1.-rand_C) + rand_A * rand_C  # [-1,1]
            inpaint_B = raw_A
            inpaint_C = rand_C.masked_fill(raw_C > 0.5, 0)  # [0,1]
            real_data = [{
                'inpaint_A': inpaint_A,
                'inpaint_B': inpaint_B,
                'inpaint_C': inpaint_C,
                'inpaint_name': raw_AC_path.split('/')[-1].replace('.png', '')
            }]

            ##------synthesis------##
            synthesis_data = []
            for idx in range(self.rate):
                synthesis_ABC_path = self.synthesis_paths[
                    index * len(self.synthesis_paths) // len(self.inpainting_paths) - idx]
                synthesis_ABC = Image.open(synthesis_ABC_path)  # PIL 0,255
                w, h = synthesis_ABC.size
                w2 = w // 3
                synthesis_A = synthesis_ABC.crop((0, 0, w2, h))
                synthesis_B = synthesis_ABC.crop((w2, 0, w2 * 2, h))
                synthesis_C = synthesis_ABC.crop((w2 * 2, 0, w, h))
                transform_paras = get_params(self.opt, synthesis_A.size)
                synthesis_transform = get_transform(self.opt, transform_paras, grayscale=True)
                synthesis_A = synthesis_transform(synthesis_A)
                synthesis_B = synthesis_transform(synthesis_B)
                synthesis_C = (synthesis_transform(synthesis_C) + 1.) * 0.5
                # kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (20, 20))
                # dilated_synthesis_C = torch.tensor(cv2.dilate(synthesis_C.view(256, 256).numpy(), kernel)).view(1, 256, 256)
                synthesis_data.append({
                    'synt_A': synthesis_A, 'synt_B': synthesis_B, 'synt_C': synthesis_C,
                })

            return real_data, synthesis_data

    def __len__(self):
        return len(self.inpainting_paths)


def get_params(opt, each_size):
    w, h = each_size
    new_h, new_w = h, w
    if opt.preprocess == 'resize_and_crop':
        new_h = new_w = opt.load_size
    elif opt.preprocess == 'scale_width_and_crop':
        new_w = opt.load_size
        new_h = opt.load_size * h // w
    x = random.randint(0, np.maximum(0, new_w - opt.crop_size))
    y = random.randint(0, np.maximum(0, new_h - opt.crop_size))

    flip_lr = random.random() > 0.5
    flip_td = False
    return {'crop_pos': (x, y), 'flip_lr': flip_lr, 'flip_td': flip_td}


def get_transform(opt, params=None, grayscale=False, method=Image.BICUBIC, convert=True):
    transform_list = []
    if grayscale:
        transform_list.append(transforms.Grayscale(1))
    if 'resize' in opt.preprocess:
        osize = [opt.load_size, opt.load_size]
        transform_list.append(transforms.Resize(osize, method))
    elif 'scale_width' in opt.preprocess:
        transform_list.append(transforms.Lambda(lambda img: __scale_width(img, opt.load_size, opt.crop_size, method)))

    if 'crop' in opt.preprocess:
        if params is None:
            transform_list.append(transforms.RandomCrop(opt.crop_size))
        else:
            transform_list.append(transforms.Lambda(lambda img: __crop(img, params['crop_pos'], opt.crop_size)))

    if not opt.no_flip:
        if params is None:
            transform_list.append(transforms.RandomHorizontalFlip())
        elif params['flip_lr']:
            transform_list.append(transforms.Lambda(lambda img: __flip_lr(img, params['flip_lr'])))
        elif params['flip_td']:
            transform_list.append(transforms.Lambda(lambda img: __flip_td(img, params['flip_td'])))

    if convert:
        transform_list += [transforms.ToTensor()]
        if grayscale:
            transform_list += [transforms.Normalize((0.5,), (0.5,))]
        else:
            transform_list += [transforms.Normalize((0.5, 0.5, 0.5), (0.5, 0.5, 0.5))]
    return transforms.Compose(transform_list)


def __flip_lr(img, flip):
    if flip:
        return img.transpose(Image.FLIP_LEFT_RIGHT)
    return img


def __flip_td(img, flip):
    if flip:
        return img.transpose(Image.FLIP_TOP_BOTTOM)
    return img


def __scale_width(img, target_size, crop_size, method=Image.BICUBIC):
    ow, oh = img.size
    if ow == target_size and oh >= crop_size:
        return img
    w = target_size
    h = int(max(target_size * oh / ow, crop_size))
    return img.resize((w, h), method)


def __crop(img, pos, size):
    ow, oh = img.size
    x1, y1 = pos
    tw = th = size
    if (ow > tw or oh > th):
        return img.crop((x1, y1, x1 + tw, y1 + th))
    return img


def __print_size_warning(ow, oh, w, h):
    """Print warning information about image size(only print once)"""
    if not hasattr(__print_size_warning, 'has_printed'):
        print("The image size needs to be a multiple of 4. "
              "The loaded image size was (%d, %d), so it was adjusted to "
              "(%d, %d). This adjustment will be done to all images "
              "whose sizes are not multiples of 4" % (ow, oh, w, h))
        __print_size_warning.has_printed = True
