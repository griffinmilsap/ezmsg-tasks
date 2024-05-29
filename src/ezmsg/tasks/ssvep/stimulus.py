import typing
import base64

from dataclasses import dataclass, field

import imageio
import numpy as np
import numpy.typing as npt

from typing import List

@dataclass(frozen = True)
class GIFStimulus:
    """
    gif is a pretty limiting format; only supports integer multiples of 10ms frame periods
    stick to reversal durations that are integer multiples of 0.01 ms > 0.02 ms
    NOTE: very few browsers support 100 fps gifs (so avoid reversal period of 0.01 ms)
    """

    duration: float = 0.08 # frame duration
    size: int = 600 # px
    border: typing.Optional[int] = None
    _src: str = field(init = False)

    def __post_init__(self) -> None:
        stim_bytes = imageio.mimwrite(
            '<bytes>',
            ims = self.images(), 
            format = 'gif', # type: ignore
            loop = 0,
            fps = int(1.0/self.duration),
        )

        stim_b64 = base64.b64encode(stim_bytes).decode("ascii")

        # Working around frozen dataclass for image caching
        object.__setattr__(self, '_src', f'data:image/gif;base64,{stim_b64}')
    
    def images(self) -> List[npt.NDArray[np.uint8]]:
        half = self.size / 2.0
        px = (np.arange(self.size) - half) / half
        x, y = np.meshgrid(px, px)
        return self.design(x, y)

    def design(self, x: npt.NDArray, y: npt.NDArray) -> List[npt.NDArray[np.uint8]]:
        raise NotImplementedError
    
    @property
    def img(self) -> str:
        border = f'border="{self.border}"' if self.border is not None else ''
        return f'<img {border} src="{self._src}"/>'
    
    def _repr_html_(self) -> str:
        return f'<center>{self.img}</center>'
    
@dataclass(frozen = True)
class MultiStimulus:
    
    stimuli: typing.List[GIFStimulus]

    def _repr_html_(self) -> str:
        images = [s.img for s in self.stimuli]
        return f"""<center>{''.join(images)}</center>"""



@dataclass(frozen = True)
class RadialCheckerboard(GIFStimulus):
    angular_freq: float = 40.0 # number of checkers around circle
    radial_freq: float = 10.0 # number of checkers to center
    radial_exp: float = 0.5 # warp factor for checker length to center

    def design(self, x: npt.NDArray, y: npt.NDArray) -> List[npt.NDArray[np.uint8]]:
        dist = np.sqrt(x**2 + y**2) ** self.radial_exp
        angle = np.arctan2(y,x)
        image = np.sin(2 * np.pi * (self.radial_freq / 2.0) * dist)
        image *= np.cos(angle * self.angular_freq / 2.0)
        image = np.sign(image)
        image[np.where(dist > 1.0)] = 0
        scale = lambda x: (x + 1.0) * ((2**7) - 1)
        return [
            scale(image).astype(np.uint8), 
            scale(image * -1).astype(np.uint8)
        ]
    
@dataclass(frozen = True)
class Rotation(GIFStimulus):

    def design(self, x: npt.NDArray, y: npt.NDArray) -> List[npt.NDArray[np.uint8]]:
        rotation_frames: int = 15
        images = [np.ones_like(x) * 2**7 for _ in range(rotation_frames)]
        for idx, image in enumerate(images):
            w = (idx * 2 * np.pi) / rotation_frames
            image[((x / np.abs(np.cos(w)))**2 + y**2) < 1.0] = int((np.cos(w) + 1.0) * (2**7-1))
        return [i.astype(np.uint8) for i in images]
    
@dataclass(frozen = True)
class Fixation(GIFStimulus):
    radius: float = 0.01 # fraction of image size

    def design(self, x: npt.NDArray, y: npt.NDArray) -> List[npt.NDArray[np.uint8]]:
        image = np.ones_like(x) * 2**7
        dist = np.sqrt(x**2 + y**2)
        image[np.where(dist < self.radius)] = 0
        return [image.astype(np.uint8)]
    
@dataclass(frozen = True)
class Blank(GIFStimulus):

    def design(self, x: npt.NDArray, y: npt.NDArray) -> List[npt.NDArray[np.uint8]]:
        image = np.ones_like(x) * 2**7
        return [image.astype(np.uint8)]



