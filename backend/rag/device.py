import torch


def safe_device() -> str:
    """Return 'cuda' only if this GPU's arch is in PyTorch's compiled arch list.

    Newer GPUs (e.g. Blackwell sm_120) can be visible to torch.cuda while the
    installed PyTorch build has no compiled kernels for them. Loading a model on
    such a device raises "CUDA error: no kernel image is available" at inference
    time, so we fall back to CPU when the arch is unsupported.
    """
    if not torch.cuda.is_available():
        return "cpu"
    try:
        major, minor = torch.cuda.get_device_capability(0)
        if f"sm_{major}{minor}" in torch.cuda.get_arch_list():
            return "cuda"
    except Exception:
        pass
    return "cpu"
