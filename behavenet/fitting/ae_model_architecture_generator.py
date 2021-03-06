import numpy as np
from behavenet.models import AE
import copy


def draw_archs(
        batch_size, input_dim, n_ae_latents, n_archs=100, check_memory=True, mem_limit_gb=5.0):
    """Generate multiple random autoencoder architectures with a fixed number of latents.

    Parameters
    ----------
    batch_size : :obj:`int`
        expected batch size, to ensure that model and intermediate values will fit on gpu
    input_dim : :obj:`array-like`
        dimensions of image with shape (n_channels, y_pix, x_pix)
    n_ae_latents : :obj:`int`
        number of autoencoder latents - fixed for all generated architectures
    n_archs : :obj:`int`, optional
        number of architectures to generate
    check_memory : :obj:`bool`, optional
        :obj:`True` to check that the memory footprint of each architecture is below a certain
        threshold
    mem_limit_gb : :obj:`float`, optional
        memory threshold in GB

    Returns
    -------
    :obj:`list` of :obj:`dict`
        list of dicts, each of which fully defines a random architecture

    """

    all_archs = []
    arch_trial_num = 0
    while len(all_archs) < n_archs:

        new_arch = get_possible_arch(input_dim, n_ae_latents, arch_seed=arch_trial_num)
        arch_trial_num += 1
        # Check max memory, keep if smaller than limit, print if rejecting
        if check_memory:
            copied_arch = copy.deepcopy(new_arch)
            copied_arch['model_class'] = 'ae'
            model = AE(copied_arch)
            mem_size = estimate_model_footprint(model, tuple([batch_size] + input_dim))
            mem_size_gb = mem_size / 1e9
            if mem_size_gb > mem_limit_gb:  # GB
                print(
                    'Model size of %02.3f GB is larger than limit of %1.3f GB;'
                    ' skipping model' % (mem_size_gb, mem_limit_gb))
                continue
            new_arch['mem_size_gb'] = mem_size_gb

        # Check against all previous arches
        matching = 0
        for prev_arch in all_archs:
            if prev_arch == new_arch:
                matching = 1
                break

        if matching == 0:
            all_archs.append(new_arch)

    return all_archs


def get_possible_arch(input_dim, n_ae_latents, arch_seed=0):
    """Generate a random autoencoder architecture.

    Parameters
    ----------
    input_dim : :obj:`array-like`
        dimensions of batch with shape (time, n_channels, y_pix, x_pix)
    n_ae_latents : :obj:`int`
        number of autoencoder latents
    arch_seed : :obj:`int`, optional
        set rng seed to reproduce architecture generation

    Returns
    -------
    :obj:`dict`
        dictionary that fully defines autoencoder architecture, which is used as input to the
        :obj:`AE` model in :obj:`behavenet.models.aes`

    """
    # Here is where you can set options/probabilities etc
    np.random.seed(arch_seed)

    # Possible options for the architecture
    opts = {}
    opts['possible_kernel_sizes'] = np.asarray([3, 5, 7, 9])
    opts['possible_strides'] = np.asarray([1, 2])  # stride will be 1 if using max pooling layers
    opts['possible_strides_probs'] = np.asarray([0.1, 0.9])
    # MAX POOL SIZE > 2 NOT IMPLEMENTED YET - NEED TO FIGURE OUT HOW TO COMBINE PADDING/CEIL MODE
    opts['possible_max_pool_sizes'] = np.asarray([2])
    opts['possible_n_channels'] = np.asarray([16, 32, 64, 128, 256, 512])
    opts['prob_stopping'] = np.arange(0, 1, .05)
    opts['max_latents'] = 64
    # probability of having FF layer at end of decoding model
    # opts['FF_layer_prob'] = 0.2
    if n_ae_latents > opts['max_latents']:
        raise ValueError('Number of latents higher than max latents')

    arch = {}
    arch['ae_input_dim'] = input_dim
    arch['model_type'] = 'conv' 
    arch['n_ae_latents'] = n_ae_latents
    arch['ae_decoding_last_FF_layer'] = 0
    # arch['ae_decoding_last_FF_layer'] = np.random.choice(
    #     np.asarray([0, 1]), p=np.asarray([1 - opts['FF_layer_prob'], opts['FF_layer_prob']]))
    arch['ae_batch_norm'] = 0 
    arch['ae_batch_norm_momentum'] = None

    # First decide if strides only or max pooling
    # network_types = ['strides_only', 'max_pooling']
    # arch['ae_network_type'] = network_types[np.random.randint(2)]
    arch['ae_network_type'] = 'strides_only'
    
    # Then decide if padding is 0 (0) or same (1) for all layers
    padding_types = ['valid', 'same']
    arch['ae_padding_type'] = padding_types[np.random.randint(2)]

    arch = get_encoding_conv_block(arch, opts)
    arch = get_decoding_conv_block(arch)

    return arch


def get_encoding_conv_block(arch, opts):
    """Build encoding block of convolutional autoencoder.

    Parameters
    ----------
    arch : :obj:`dict`
        specifies basic architecture details used throughout encoder such as padding type ('same'
        vs 'valid'), presence of max pooling layers, etc.
    opts : :obj:`dict`
        specifies hyperparameter options and ranges (e.g. possible kernel sizes, strides, channels)

    Returns
    -------
    :obj:`dict`
        updated architecture dict fully specifying encoder hyperparameters

    """

    last_dims = arch['ae_input_dim'][0] * arch['ae_input_dim'][1] * arch['ae_input_dim'][2]
    smallest_pix = min(arch['ae_input_dim'][1], arch['ae_input_dim'][2])

    arch['ae_encoding_x_dim'] = []
    arch['ae_encoding_y_dim'] = []

    arch['ae_encoding_n_channels'] = []
    arch['ae_encoding_kernel_size'] = []
    arch['ae_encoding_stride_size'] = []
    arch['ae_encoding_x_padding'] = []
    arch['ae_encoding_y_padding'] = []
    arch['ae_encoding_layer_type'] = []

    i_layer = 0
    global_layer = 0
    while last_dims >= opts['max_latents'] and smallest_pix >= 1:

        # Get conv2d layer
        kernel_size = np.random.choice(opts['possible_kernel_sizes'])
        if arch['ae_network_type'] == 'strides_only':
            stride_size = np.random.choice(
                opts['possible_strides'], p=opts['possible_strides_probs'])
        else:
            stride_size = 1  # use stride of 1 with max pooling layers

        if i_layer == 0:  # use input dimensions
            input_dim_y = arch['ae_input_dim'][1]
            input_dim_x = arch['ae_input_dim'][2]
        else:
            input_dim_y = arch['ae_encoding_y_dim'][i_layer - 1]
            input_dim_x = arch['ae_encoding_x_dim'][i_layer - 1]

        output_dim_y, y_before_pad, y_after_pad = calculate_output_dim(
            input_dim_y, kernel_size, stride_size, padding_type=arch['ae_padding_type'],
            layer_type='conv')
        output_dim_x, x_before_pad, x_after_pad = calculate_output_dim(
            input_dim_x, kernel_size, stride_size, padding_type=arch['ae_padding_type'],
            layer_type='conv')

        if i_layer == 0:
            idxs = opts['possible_n_channels'] >= arch['ae_input_dim'][0]
            remaining_channels = opts['possible_n_channels'][idxs]
        else:
            idxs = opts['possible_n_channels'] >= arch['ae_encoding_n_channels'][i_layer - 1]
            remaining_channels = opts['possible_n_channels'][idxs]

        if len(remaining_channels) > 1:
            prob_channels = [.75] + \
                [.25 / (len(remaining_channels) - 1) for _ in range(len(remaining_channels) - 1)]
        else:
            prob_channels = [1]

        n_channels = np.random.choice(remaining_channels, p=prob_channels)

        if np.prod(n_channels * output_dim_x * output_dim_y) >= opts['max_latents'] and \
                np.min([output_dim_x, output_dim_y]) >= 1:
            # Choices ahead of time
            arch['ae_encoding_n_channels'].append(n_channels)
            arch['ae_encoding_kernel_size'].append(kernel_size)
            arch['ae_encoding_stride_size'].append(stride_size)
            # Automatically calculated
            arch['ae_encoding_x_dim'].append(output_dim_x)
            arch['ae_encoding_y_dim'].append(output_dim_y)
            arch['ae_encoding_x_padding'].append((x_before_pad, x_after_pad))
            arch['ae_encoding_y_padding'].append((y_before_pad, y_after_pad))
            arch['ae_encoding_layer_type'].append('conv')
            i_layer += 1
        else:
            break

        # Get max pool layer if applicable
        if arch['ae_network_type'] == 'max_pooling':
            kernel_size = np.random.choice(opts['possible_max_pool_sizes'])

            output_dim_y, y_before_pad, y_after_pad = calculate_output_dim(
                arch['ae_encoding_y_dim'][i_layer - 1], kernel_size, kernel_size,
                padding_type=arch['ae_padding_type'], layer_type='maxpool')
            output_dim_x, x_before_pad, x_after_pad = calculate_output_dim(
                arch['ae_encoding_x_dim'][i_layer - 1], kernel_size, kernel_size,
                padding_type=arch['ae_padding_type'], layer_type='maxpool')

            if np.prod(n_channels * output_dim_x * output_dim_y) >= opts['max_latents'] and \
                    np.min([output_dim_x, output_dim_y]) >= 1:

                arch['ae_encoding_n_channels'].append(n_channels)
                arch['ae_encoding_kernel_size'].append(kernel_size)
                arch['ae_encoding_stride_size'].append(
                    kernel_size)  # for max pool layers have stride as kernel size
                arch['ae_encoding_x_padding'].append((x_before_pad, x_after_pad))
                arch['ae_encoding_y_padding'].append((y_before_pad, y_after_pad))
                arch['ae_encoding_x_dim'].append(output_dim_x)
                arch['ae_encoding_y_dim'].append(output_dim_y)
                arch['ae_encoding_layer_type'].append('maxpool')

                i_layer += 1
            else:
                # Delete previous conv layer
                arch['ae_encoding_n_channels'] = arch['ae_encoding_n_channels'][:-1]
                arch['ae_encoding_kernel_size'] = arch['ae_encoding_kernel_size'][:-1]
                arch['ae_encoding_stride_size'] = arch['ae_encoding_stride_size'][:-1]
                arch['ae_encoding_x_padding'] = arch['ae_encoding_x_padding'][:-1]
                arch['ae_encoding_y_padding'] = arch['ae_encoding_y_padding'][:-1]
                arch['ae_encoding_x_dim'] = arch['ae_encoding_x_dim'][:-1]
                arch['ae_encoding_y_dim'] = arch['ae_encoding_y_dim'][:-1]
                arch['ae_encoding_layer_type'] = arch['ae_encoding_layer_type'][:-1]
                break

        last_dims = arch['ae_encoding_n_channels'][-1] * arch['ae_encoding_y_dim'][-1] * \
                    arch['ae_encoding_x_dim'][-1]
        smallest_pix = min(arch['ae_encoding_y_dim'][-1], arch['ae_encoding_x_dim'][-1])
        stop_this_layer = np.random.choice(
            [0, 1],
            p=[1 - opts['prob_stopping'][global_layer], opts['prob_stopping'][global_layer]])

        if stop_this_layer:
            break

        global_layer += 1

    return arch


def get_decoding_conv_block(arch):
    """Build symmetric decoding block of convolutional autoencoder based on encoding block.

    Parameters
    ----------
    arch : :obj:`dict`
        specifies architecture details of encoding block; the decoding block is constructed to be
        symmetric (replacing conv2d with conv2d_transpose layers, etc.)

    Returns
    -------
    :obj:`dict`
        updated architecture dict fully specifying encoder and decoder hyperparameters

    """

    arch['ae_decoding_x_dim'] = []
    arch['ae_decoding_y_dim'] = []
    arch['ae_decoding_x_padding'] = []
    arch['ae_decoding_y_padding'] = []

    arch['ae_decoding_n_channels'] = []
    arch['ae_decoding_kernel_size'] = []
    arch['ae_decoding_stride_size'] = []

    arch['ae_decoding_layer_type'] = []

    arch['ae_decoding_starting_dim'] = [
        arch['ae_encoding_n_channels'][-1],
        arch['ae_encoding_y_dim'][-1],
        arch['ae_encoding_x_dim'][-1]]

    encoding_layer_num_vec = np.arange(len(arch['ae_encoding_n_channels']) - 1, -1, -1)

    i_layer = 0
    for which_encoding_layer in encoding_layer_num_vec:

        if which_encoding_layer == 0:
            arch['ae_decoding_n_channels'].append(arch['ae_input_dim'][0])
        else:
            arch['ae_decoding_n_channels'].append(
                arch['ae_encoding_n_channels'][which_encoding_layer - 1])

        arch['ae_decoding_kernel_size'].append(
            arch['ae_encoding_kernel_size'][which_encoding_layer])
        arch['ae_decoding_stride_size'].append(
            arch['ae_encoding_stride_size'][which_encoding_layer])
        arch['ae_decoding_x_padding'].append(
            arch['ae_encoding_x_padding'][which_encoding_layer])
        arch['ae_decoding_y_padding'].append(
            arch['ae_encoding_y_padding'][which_encoding_layer])

        if which_encoding_layer > 0:
            output_dim_y = arch['ae_encoding_y_dim'][which_encoding_layer - 1]
            output_dim_x = arch['ae_encoding_x_dim'][which_encoding_layer - 1]
        else:
            output_dim_y = arch['ae_input_dim'][1]
            output_dim_x = arch['ae_input_dim'][2]

        arch['ae_decoding_y_dim'].append(output_dim_y)
        arch['ae_decoding_x_dim'].append(output_dim_x)

        if arch['ae_encoding_layer_type'][which_encoding_layer] == 'maxpool':
            arch['ae_decoding_layer_type'].append('unpool')
        elif arch['ae_encoding_layer_type'][which_encoding_layer] == 'conv':  # if conv layer
            arch['ae_decoding_layer_type'].append('convtranspose')

        i_layer += 1

    if arch['ae_decoding_last_FF_layer']:
        # if ff layer at end, use 16 channels for final conv layer to reduce param count
        arch['ae_decoding_n_channels'][-1] = 16

    return arch


def calculate_output_dim(input_dim, kernel, stride, padding_type, layer_type):
    """Calculate output dimension of a layer/dimension based on input size, kernel size, etc.

    Inspired by:
        - https://github.com/tensorflow/tensorflow/blob/master/tensorflow/core/framework/common_shape_fns.cc#L21
        - https://github.com/pytorch/pytorch/issues/3867

    Parameters
    ----------
    input_dim : :obj:`int`
        single spatial dimension
    kernel : :obj:`int`
        kernel size
    stride : :obj:`int`
        stride length
    padding_type : :obj:`str`
        'same' | 'valid'
    layer_type : :obj:`str`
        'conv' | 'maxpool'

    Returns
    -------
    :obj:`tuple`
        - output dim (:obj:`int`)
        - before pad (:obj:`int`)
        - after pad (:obj:`int`)

    """

    if layer_type == 'conv':

        if padding_type == 'same':
            output_dim = (input_dim + stride - 1) // stride
            total_padding_needed = max(0, (output_dim - 1) * stride + kernel - input_dim)
            before_pad = total_padding_needed // 2
            after_pad = total_padding_needed - before_pad
        elif padding_type == 'valid':
            output_dim = int(np.floor((input_dim - kernel) / stride + 1))
            before_pad = 0
            after_pad = 0
        else:
            raise NotImplementedError

    elif layer_type == 'maxpool':

        if kernel != 2:
            raise NotImplementedError

        if padding_type == 'same':
            output_dim = int(np.ceil((input_dim - kernel) / stride + 1))
            before_pad = 0
            after_pad = 0
        elif padding_type == 'valid':
            output_dim = int(np.floor((input_dim - kernel) / stride + 1))
            before_pad = 0
            after_pad = 0
        else:
            raise NotImplementedError

    else:
        raise NotImplementedError

    return output_dim, before_pad, after_pad


def estimate_model_footprint(model, input_dim, cutoff_size=20):
    """Estimate model size to determine if it will fit on a single GPU.

    Adapted from http://jacobkimmel.github.io/pytorch_estimating_model_size/.

    The estimation:
    - assumes the model (autoencoder) is symmetric
    - assumes all values (data/parameters) are float32
    - accounts for size of input data
    - accounts for storage of intermediate layer values and gradients
    - adds an additional 20% fudge factor

    Parameters
    ----------
    model : pytorch model
    input_dim : :obj:`array-like`
        dimensions of batch with shape (time, n_channels, y_pix, x_pix)
    cutoff_size : :obj:`float`, optional
        terminate estimation once model size grows beyond this point (GB)

    Returns
    -------
    :obj:`int`
        estimated size of model in bytes

    """

    import torch
    from torch.autograd import Variable

    allowed_modules = (
        torch.nn.Conv2d,
        torch.nn.ConvTranspose2d,
        torch.nn.MaxPool2d,
        torch.nn.MaxUnpool2d,
        torch.nn.Linear)

    curr_bytes = 0

    # assume everything is float32
    bytes = 4

    # estimate input size
    curr_bytes += np.prod(input_dim) * bytes

    # estimate model size
    mods = list(model.modules())
    for mod in mods:
        if isinstance(mod, allowed_modules):
            p = list(mod.parameters())
            for p_ in p:
                curr_bytes += np.prod(np.array(p_.size())) * bytes

    # estimate intermediate size
    x = Variable(torch.FloatTensor(*input_dim))
    for layer in model.encoding.encoder:
        if isinstance(layer, torch.nn.MaxPool2d):
            x, idx = layer(x)
        else:
            x = layer(x)
        # multiply by 2 - assume decoder is symmetric
        # multiply by 2 - we need to store values AND gradients
        curr_bytes += np.prod(x.size()) * bytes * 2 * 2
        if curr_bytes / 1e9 > cutoff_size:
            break

    return curr_bytes * 1.2  # safety blanket


def get_handcrafted_dims(arch, symmetric=True):
    """Compute input/output dims as well as necessary padding for handcrafted architectures.

    If :obj:`symmetric=True`, calculate decoding block based on encoding block. :obj:`arch` needs
    to have padding_type, ae_encoding_n_channels, ae_encoding_kernel_size, ae_encoding_stride_size,
    ae_encoding_layer type, ae_batch_norm, ae_n_latents, ae_decoding_last_FF_layer, ae_input_dim

    If :obj:`symmetric=False`, :obj:`arch` also needs to have ae_decoding_n_channels,
    ae_decoding_kernel_size, ae_decoding_stride_size, ae_decoding_layer_type,
    ae_decoding_starting_dim

    Assumes output padding is 0.

    Parameters
    ----------
    arch : :obj:`dict`
        specifies model architecture; see above for required keys
    symmetric : :obj:`bool`, optional
        determines whether or not to create symmetric architecture

    Returns
    -------
    :obj:`dict`
        updated architecture dict fully specifying encoder and decoder hyperparameters

    """

    arch['model_type'] = 'conv'
    
    arch['ae_encoding_x_dim'] = []
    arch['ae_encoding_y_dim'] = []
    arch['ae_encoding_x_padding'] = []
    arch['ae_encoding_y_padding'] = []

    for i_layer in range(len(arch['ae_encoding_n_channels'])):
        
        kernel_size = arch['ae_encoding_kernel_size'][i_layer]
        stride_size = arch['ae_encoding_stride_size'][i_layer]
        
        if i_layer == 0:  # use input dimensions
            input_dim_y = arch['ae_input_dim'][1]
            input_dim_x = arch['ae_input_dim'][2]
        else:
            input_dim_y = arch['ae_encoding_y_dim'][i_layer-1]
            input_dim_x = arch['ae_encoding_x_dim'][i_layer-1]

        output_dim_x, x_before_pad, x_after_pad = calculate_output_dim(
            input_dim_x, kernel_size, stride_size, padding_type=arch['ae_padding_type'],
            layer_type=arch['ae_encoding_layer_type'][i_layer])
        output_dim_y, y_before_pad, y_after_pad = calculate_output_dim(
            input_dim_y, kernel_size, stride_size, padding_type=arch['ae_padding_type'],
            layer_type=arch['ae_encoding_layer_type'][i_layer])

        arch['ae_encoding_x_dim'].append(output_dim_x)
        arch['ae_encoding_y_dim'].append(output_dim_y)
        arch['ae_encoding_x_padding'].append((x_before_pad,x_after_pad))
        arch['ae_encoding_y_padding'].append((y_before_pad,y_after_pad))

    if symmetric:
        arch = get_decoding_conv_block(arch)
    else:
        # If any unpooling layers, can't do this way as have to match up max pooling and unpooling
        # layer
        if arch['ae_network_type'] == 'max_pooling' or \
                np.sum(np.asarray(arch['ae_decoding_layer_type']) == 'unpool'):
            raise NotImplementedError
        arch['ae_decoding_x_dim'] = []
        arch['ae_decoding_y_dim'] = []
        arch['ae_decoding_x_padding'] = []
        arch['ae_decoding_y_padding'] = []

        for i_layer in range(len(arch['ae_decoding_n_channels'])):
            kernel_size = arch['ae_decoding_kernel_size'][i_layer]
            stride_size = arch['ae_decoding_stride_size'][i_layer]
        
            if i_layer == 0:  # use input dimensions
                input_dim_y = arch['ae_decoding_starting_dim'][1]
                input_dim_x = arch['ae_decoding_starting_dim'][2]
            else:
                input_dim_y = arch['ae_decoding_y_dim'][i_layer-1]
                input_dim_x = arch['ae_decoding_x_dim'][i_layer-1]

            if arch['ae_padding_type'] == 'valid':
                before_pad = 0
                after_pad = 0
            elif arch['ae_padding_type'] == 'same':
                output_dim_x = input_dim_x * stride_size - stride_size + 1
                output_dim_y = input_dim_y * stride_size - stride_size + 1
                total_padding_needed_x = max(
                    0, (input_dim_x - 1) * stride_size + kernel_size - output_dim_x)
                total_padding_needed_y = max(
                    0, (input_dim_y - 1) * stride_size + kernel_size - output_dim_y)
                x_before_pad = total_padding_needed_x // 2
                y_before_pad = total_padding_needed_y // 2
                x_after_pad = total_padding_needed_x - x_before_pad
                y_after_pad = total_padding_needed_x - y_before_pad
                arch['ae_decoding_x_dim'].append(output_dim_x)
                arch['ae_decoding_y_dim'].append(output_dim_y)
                arch['ae_decoding_x_padding'].append((x_before_pad, x_after_pad))
                arch['ae_decoding_y_padding'].append((y_before_pad, y_after_pad))
    return arch


def draw_handcrafted_archs(
        input_dim, n_ae_latents, which_archs, batch_size=None, check_memory=True,
        mem_limit_gb=None):
    """Generate handcrafted autoencoder architectures with a fixed number of latents.

    The original behavenet paper (Neurips 2019) used architecture 0 below.

    Examples
    --------

    Architecture 0
        - max_pooling: False
        - batch_norm: False
        - padding type: 'same'
        - layer types: ['conv', 'conv', 'conv', 'conv']
        - n_channels: [32, 64, 256, 512]
        - kernel_size: [5, 5, 5, 5]
        - stride_size: [2, 2, 2, 2]
        - decoding module is symmetric to encoding module
        - final dense ff layer: False
        - Architecture -1 is the same as this but with batch norm enabled

    Architecture 1:
        - max_pooling: False
        - batch_norm: False
        - padding type: 'same'
        - layer types: ['conv', 'conv', 'conv', 'conv', 'conv']
        - n_channels: [64, 64, 64, 64, 64]
        - kernel_size: [5, 5, 5, 5, 5]
        - stride_size: [2, 2, 2, 2, 1]
        - decoding module is symmetric to encoding module
        - final dense ff layer: False

    Architecture 2:
        - max_pooling: False
        - batch_norm: False
        - padding type: 'same'
        - encoding layer types: ['conv', 'conv', 'conv', 'conv', 'conv']
        - encoding n_channels: [64, 64, 64, 64, 64]
        - encoding kernel_size: [4, 4, 4, 4, 4]
        - encoding stride_size: [2, 2, 2, 2, 1]
        - decoding layer types: ['convtranspose', 'convtranspose', 'convtranspose']
        - decoding n_channels: [64, 64, 64]
        - decoding kernel_size: [4, 4, 4]
        - decoding stride_size: [2, 1, 1]
        - final dense ff layer: True

    Parameters
    ----------
    input_dim : :obj:`array-like`
        dimensions of image with shape (n_channels, y_pix, x_pix)
    n_ae_latents : :obj:`int`
        number of autoencoder latents - fixed for all generated architectures
    which_archs : :obj:`list`
        which architectures to generate
    batch_size : :obj:`int`, optional
        expected batch size, to ensure that model and intermediate values will fit on gpu
    check_memory : :obj:`bool`, optional
        :obj:`True` to check that the memory footprint of each architecture is below a certain
        threshold
    mem_limit_gb : :obj:`float`, optional
        memory threshold in GB

    Returns
    -------
    :obj:`list` of :obj:`dict`
        list of dicts, each of which fully defines a handcrafted architecture

    """

    # TODO: how to let user easily add their own handcrafted architecture?

    list_of_handcrafted_archs = []
    max_latents = 64  # make sure no bottleneck smaller than this

    # if n_ae_latents > max_latents:
    #     raise ValueError('Number of latents higher than max latents')

    # Architecture -1 (similar to Ella's old architecture, plus batch norm)
    if np.any(which_archs == -1):

        arch = {}

        arch['n_input_channels'] = input_dim[0]
        arch['y_pixels'] = input_dim[1]
        arch['x_pixels'] = input_dim[2]

        arch['ae_input_dim'] = input_dim
        arch['n_ae_latents'] = n_ae_latents

        arch['ae_network_type'] = 'strides_only'
        arch['ae_padding_type'] = 'same'

        arch['ae_encoding_n_channels'] = [32, 64, 256, 512]
        arch['ae_encoding_kernel_size'] = [5, 5, 5, 5]
        arch['ae_encoding_stride_size'] = [2, 2, 2, 2]
        arch['ae_encoding_layer_type'] = ['conv', 'conv', 'conv', 'conv']

        arch['ae_batch_norm'] = True
        arch['ae_batch_norm_momentum'] = None
        arch['ae_decoding_last_FF_layer'] = 0

        arch = get_handcrafted_dims(arch, symmetric=True)
        if (arch['ae_encoding_n_channels'][-1]
                * arch['ae_encoding_x_dim'][-1]
                * arch['ae_encoding_y_dim'][-1]) < max_latents:
            raise ValueError('Bottleneck smaller than number of latents')

        list_of_handcrafted_archs.append(arch)

    # Architecture 0 (similar to Ella's old architecture from Win)
    if np.any(which_archs == 0):

        arch = {}

        arch['n_input_channels'] = input_dim[0]
        arch['y_pixels'] = input_dim[1]
        arch['x_pixels'] = input_dim[2]

        arch['ae_input_dim'] = input_dim
        #arch['n_ae_latents'] = n_ae_latents

        arch['ae_network_type'] = 'strides_only'
        arch['ae_padding_type'] = 'same'

        arch['ae_encoding_n_channels'] = [32, 64, 256, 512]
        arch['ae_encoding_kernel_size'] = [5, 5, 5, 5]
        arch['ae_encoding_stride_size'] = [2, 2, 2, 2]
        arch['ae_encoding_layer_type'] = ['conv', 'conv', 'conv', 'conv']

        arch['ae_batch_norm'] = False
        arch['ae_batch_norm_momentum'] = None
        arch['ae_decoding_last_FF_layer'] = 0

        arch = get_handcrafted_dims(arch, symmetric=True)
        if (arch['ae_encoding_n_channels'][-1]
                * arch['ae_encoding_x_dim'][-1]
                * arch['ae_encoding_y_dim'][-1]) < max_latents:
            raise ValueError('Bottleneck smaller than number of latents')

        list_of_handcrafted_archs.append(arch)

    # Architecture 1 (Matt's encoder with different symmetric decoder)
    if np.any(which_archs == 1):

        arch = {}

        arch['n_input_channels'] = input_dim[0]
        arch['y_pixels'] = input_dim[1]
        arch['x_pixels'] = input_dim[2]

        arch['ae_input_dim'] = input_dim
        arch['n_ae_latents'] = n_ae_latents

        arch['ae_network_type'] = 'strides_only'
        arch['ae_padding_type'] = 'same'

        arch['ae_encoding_n_channels'] = [64, 64, 64, 64, 64]
        arch['ae_encoding_kernel_size'] = [5, 5, 5, 5, 5]
        arch['ae_encoding_stride_size'] = [2, 2, 2, 2, 1]
        arch['ae_encoding_layer_type'] = ['conv', 'conv', 'conv', 'conv', 'conv']

        arch['ae_batch_norm'] = False
        arch['ae_batch_norm_momentum'] = None
        arch['ae_decoding_last_FF_layer'] = 0

        arch = get_handcrafted_dims(arch, symmetric=True)
        if (arch['ae_encoding_n_channels'][-1]
                * arch['ae_encoding_x_dim'][-1]
                * arch['ae_encoding_y_dim'][-1]) < max_latents:
            raise ValueError('Bottleneck smaller than number of latents')

        list_of_handcrafted_archs.append(arch)

    # Architecture 2 (Matt's architecture)
    if np.any(which_archs == 2):

        arch = {}

        arch['n_input_channels'] = input_dim[0]
        arch['y_pixels'] = input_dim[1]
        arch['x_pixels'] = input_dim[2]

        arch['ae_input_dim'] = input_dim
        arch['n_ae_latents'] = n_ae_latents

        arch['ae_network_type'] = 'strides_only'
        arch['ae_padding_type'] = 'same'

        arch['ae_encoding_n_channels'] = [64, 64, 64, 64, 64]
        arch['ae_encoding_kernel_size'] = [4, 4, 4, 4, 4]
        arch['ae_encoding_stride_size'] = [2, 2, 2, 2, 1]
        arch['ae_encoding_layer_type'] = ['conv', 'conv', 'conv', 'conv', 'conv']

        arch['ae_batch_norm'] = 0
        arch['ae_decoding_last_FF_layer'] = 1

        # set inputs to the decoder
        # we first have one fully connected layer with
        # batch_size X (reshape_size*reshape_size) X channels shape
        # and then reshape to
        # batch_size X reshape_size X reshape_size X channels
        integers = np.arange(1, 11)
        two_powers = 2 ** integers
        self_powers = two_powers ** 2
        # make sure we are not shrinking to something smaller than n_latent
        ind_min_input = np.argmax(self_powers >= n_ae_latents)
        reshape_size = two_powers[ind_min_input]
        arch['ae_decoding_starting_dim'] = [1, reshape_size, reshape_size]
        arch['ae_decoding_n_channels'] = [64, 64, 64]
        arch['ae_decoding_kernel_size'] = [4, 4, 4]
        arch['ae_decoding_stride_size'] = [2, 1, 1]
        arch['ae_decoding_layer_type'] = ['convtranspose', 'convtranspose', 'convtranspose']

        arch = get_handcrafted_dims(arch, symmetric=False)
        if (arch['ae_encoding_n_channels'][-1]
                * arch['ae_encoding_x_dim'][-1]
                * arch['ae_encoding_y_dim'][-1]) < max_latents:
            raise ValueError('Bottleneck smaller than number of latents')

        list_of_handcrafted_archs.append(arch)

    # if check_memory:
    #     for i, new_arch in enumerate(list_of_handcrafted_archs):
    #         copied_arch = copy.deepcopy(new_arch)
    #         copied_arch['model_class'] = 'ae'
    #         model = AE(copied_arch)
    #         mem_size = estimate_model_footprint(model, tuple([batch_size] + input_dim))
    #         mem_size_gb = mem_size / 1e9
    #         if mem_size_gb > mem_limit_gb:  # GB
    #             raise ValueError('Handcrafted architecture %i too big for memory' % which_archs[i])
    #         new_arch['mem_size_gb'] = mem_size_gb

    return list_of_handcrafted_archs
