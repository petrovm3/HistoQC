import os
import sys

from ast import literal_eval as make_tuple

from distutils.util import strtobool

from skimage import io
from skimage.filters import gabor_kernel, frangi, gaussian, median, laplace
from skimage.color import rgb2gray
from skimage.morphology import remove_small_objects, disk
from skimage.feature import local_binary_pattern

from scipy import ndimage as ndi

from sklearn.naive_bayes import GaussianNB
from sklearn.ensemble import RandomForestClassifier

import numpy as np

import matplotlib.pyplot as plt

global_holder = {}


def pixelWise(s, params):
    name = params.get("name", "classTask")
    print("\tpixelWise:\t", name)

    thresh = float(params.get("threshold", .5))

    fname = params.get("tsv_file", "")
    if fname == "":
        print("tsv_file not set in ClassificationModule.pixelWise for ", name)
        sys.exit(1)
        return
    model_vals = np.loadtxt(fname, delimiter="\t", skiprows=1)

    img = s.getImgThumb(s["image_work_size"])

    gnb = GaussianNB()
    gnb.fit(model_vals[:, 1:], model_vals[:, 0])
    cal = gnb.predict_proba(img.reshape(-1, 3))

    cal = cal.reshape(img.shape[0], img.shape[1], 2)
    mask = cal[:, :, 1] > thresh

    mask = s["img_mask_use"] & (mask > 0)

    s.addToPrintList(name, str(mask.mean()))
    io.imsave(s["outdir"] + os.sep + s["filename"] + "_" + name + ".png", mask * 255)
    s["img_mask_" + name] = (mask * 255) > 0
    s["img_mask_use"] = s["img_mask_use"] & ~s["img_mask_" + name]

    return


# extract_patches_2d(image, patch_size, max_patches=None, random_state=None

def compute_rgb(img, params):
    return img



def compute_laplace(img,params):
    laplace_ksize= int(params.get("laplace_ksize", 3))
    return laplace(rgb2gray(img), ksize=laplace_ksize)[:, :, None]

def compute_lbp(img, params):
    lbp_radius = float(params.get("lbp_radius", 3))
    lbp_points = int(params.get("lbp_points", 24)) #example sets radius * 8
    lbp_method = params.get("lbp_method", "default")

    return local_binary_pattern(rgb2gray(img), P=lbp_points, R=lbp_radius, method=lbp_method)[:, :, None]


def compute_gaussian(img, params):
    gaussian_sigma = int(params.get("gaussian_sigma ", 1))
    gaussian_multichan = strtobool(params.get("gaussian_multichan", False))

    if (gaussian_multichan):
        return gaussian(img, sigma=gaussian_sigma, multichannel=gaussian_multichan)
    else:
        return gaussian(rgb2gray(img), sigma=gaussian_sigma)[:, :, None]


def compute_median(img, params):
    median_disk_size = int(params.get("median_disk_size", 3))
    return median(rgb2gray(img), selem=disk(median_disk_size))[:, :, None]


def compute_gabor(img, params):
    if not global_holder.get("gabor_kernels", False):
        gabor_theta = int(params.get("gabor_theta", 4))
        gabor_sigma = make_tuple(params.get("gabor_sigma", "(1,3)"))
        gabor_frequency = make_tuple(params.get("gabor_frequency", "(0.05, 0.25)"))

        kernels = []
        for theta in range(gabor_theta):
            theta = theta / 4. * np.pi
            for sigma in gabor_sigma:
                for frequency in gabor_frequency:
                    kernel = np.real(gabor_kernel(frequency, theta=theta,
                                                  sigma_x=sigma, sigma_y=sigma))
                    kernels.append(kernel)
        global_holder["gabor_kernels"] = kernels

    imgg = rgb2gray(img)
    feats = np.zeros((imgg.shape[0], imgg.shape[1], len(kernels)), dtype=np.double)
    for k, kernel in enumerate(kernels):
        filtered = ndi.convolve(imgg, kernel, mode='wrap')
        feats[:, :, k] = filtered
    return feats


def compute_frangi(img, params):
    frangi_scale_range = make_tuple(params.get("frangi_scale_range", "(1, 10)"))
    frangi_scale_step = float(params.get("frangi_scale_step", 2))
    frangi_beta1 = float(params.get("frangi_beta1", .5))
    frangi_beta2 = float(params.get("frangi_beta2", 15))
    frangi_black_ridges = strtobool(params.get("frangi_black_ridges", "True"))
    feat = frangi(rgb2gray(img), frangi_scale_range, frangi_scale_step, frangi_beta1, frangi_beta2, frangi_black_ridges)
    return feat[:, :, None]  # add singleton dimension


def compute_features(img, params):
    features = params.get("features", "")

    feats = []
    for feature in features.splitlines():
        func = getattr(sys.modules[__name__], f"compute_{feature}")
        feats.append(func(img, params))

    return np.concatenate(feats, axis=2)


def byExampleWithFeatures(s, params):
    name = params.get("name", "classTask")
    print("\tClassificationModule.byExample:\t", name)

    thresh = float(params.get("threshold", .5))

    examples = params.get("examples", "")
    if examples == "":
        print("No examples provided in ClassificationModule.byExample for ", name, "!!")
        sys.exit(1)
        return

    if params.get("features", "") == "":
        print("No features provided in ClassificationModule.byExample for ", name, "!!")
        sys.exit(1)
        return

    if not global_holder.get("model_" + name, False):

        model_vals = []
        model_labels = np.empty([0, 1])

        for ex in params["examples"].splitlines():
            ex = ex.split(":")
            img = io.imread(ex[0])
            eximg = compute_features(img, params)
            eximg = eximg.reshape(-1, eximg.shape[2])
            model_vals.append(eximg)

            mask = io.imread(ex[1]).reshape(-1, 1)
            model_labels = np.vstack((model_labels, mask))

        # do stuff here with model_vals
        model_vals = np.vstack(model_vals)
        clf = RandomForestClassifier(n_jobs=-1)
        clf.fit(model_vals, model_labels.ravel())
        global_holder["model_" + name] = clf

    clf = global_holder["model_" + name]
    img = s.getImgThumb(s["image_work_size"])
    feats = compute_features(img, params)
    cal = clf.predict_proba(feats.reshape(-1, feats.shape[2]))
    cal = cal.reshape(img.shape[0], img.shape[1], 2)

    mask = cal[:, :, 1] > thresh

    if params.get("area_thresh", "") != "":
        mask = remove_small_objects(mask, min_size=int(params.get("area_thresh", "")), in_place=True)

    mask = s["img_mask_use"] & (mask > 0)

    s.addToPrintList(name, str(mask.mean()))
    io.imsave(s["outdir"] + os.sep + s["filename"] + "_" + name + ".png", mask * 255)
    s["img_mask_" + name] = (mask * 255) > 0
    s["img_mask_use"] = s["img_mask_use"] & ~s["img_mask_" + name]

    return