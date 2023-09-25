import cudnn
import pytest
import torch

def convert_to_cudnn_type(torch_type):
    if torch_type == torch.float16:
        return cudnn.data_type.HALF
    elif torch_type == torch.float32:
        return cudnn.data_type.FLOAT
    else:
        raise ValueError("Unsupported tensor data type.")


def test_reduction():
    # Define tensor dimensions
    N, K, C, H, W = 4, 32, 16, 64, 64
    R, S = 3, 3
    padding = stride = dilation = [1, 1]

    # Reference
    X_gpu = torch.randn(N, C, H, W, dtype=torch.float16, device='cuda').to(memory_format=torch.channels_last)
    W_gpu = torch.randn(K, C, R, S, dtype=torch.float16, device='cuda').to(memory_format=torch.channels_last)
    # Perform convolution using FP32 computation while input and filter remain in FP16
    with torch.cuda.amp.autocast(dtype=torch.float32):
        conv_output = torch.nn.functional.conv2d(X_gpu, W_gpu, padding=padding, stride=stride, dilation=dilation)
        Y_expected = conv_output.sum(dim=1)

    # Cudnn code
    graph = cudnn.pygraph(io_data_type = cudnn.data_type.HALF, intermediate_data_type = cudnn.data_type.FLOAT, compute_data_type = cudnn.data_type.FLOAT)
    X = graph.tensor(name = "X", dim = X_gpu.size(), stride = X_gpu.stride(), data_type = convert_to_cudnn_type(X_gpu.dtype))
    Weight = graph.tensor(name = "W", dim = W_gpu.size(), stride = W_gpu.stride(), data_type = convert_to_cudnn_type(W_gpu.dtype))

    Y0 = graph.conv_fprop(image = X, weight = Weight, padding = padding, stride = stride, dilation = dilation)
    
    Y = graph.reduction(input = Y0, mode = cudnn.reduction_mode.ADD)
    Y.set_output(True).set_dim([N,1,H,W]).set_data_type(cudnn.data_type.FLOAT)

    graph.check_support()
    
    graph.build()

    Y_actual   = torch.zeros_like(Y_expected)

    workspace = torch.empty(graph.get_workspace_size(), device="cuda", dtype=torch.uint8)

    graph.execute({X: X_gpu, Weight: W_gpu, Y: Y_actual}, workspace)

    # Compare
    torch.testing.assert_close(Y_expected,        Y_actual, atol=1e-3, rtol=1e-3)

if __name__ == "__main__":
    test_reduction()