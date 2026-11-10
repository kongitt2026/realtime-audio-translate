# 实时翻译模块 · ffmpeg 二进制解析
# 优先级：系统 PATH → imageio-ffmpeg 内置二进制（与漫剧流水线同一来源）

import shutil


def get_ffmpeg() -> str:
    sys_ff = shutil.which("ffmpeg")
    if sys_ff:
        return sys_ff
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()
