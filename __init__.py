from comfy_api.latest import ComfyExtension, io

from .vfx_naming import VFXNamingConvention

WEB_DIRECTORY = "./web"


class VFXNamingExtension(ComfyExtension):
    async def get_node_list(self) -> list[type[io.ComfyNode]]:
        return [VFXNamingConvention]


async def comfy_entrypoint() -> ComfyExtension:
    return VFXNamingExtension()


__all__ = ["comfy_entrypoint", "WEB_DIRECTORY"]
