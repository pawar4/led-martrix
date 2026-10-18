"""A canvas that draws only inside a rectangle, so a `Scroll` can show part of a taller piece of the screen."""


class ClipCanvas:
    """Passes `SetPixel` through to `target` for pixels inside `clip` (a Rect) and drops the rest. `width` and
    `height` are the target's. Code that must hand the real canvas to native drawing (`graphics.DrawText`) uses
    `target`."""

    def __init__(self, target, clip):
        self.target = target
        self.clip = clip

    @property
    def width(self):
        return self.target.width

    @property
    def height(self):
        return self.target.height

    def SetPixel(self, x, y, r, g, b):
        clip = self.clip
        if clip.x <= x < clip.x + clip.w and clip.y <= y < clip.y + clip.h:
            self.target.SetPixel(x, y, r, g, b)
