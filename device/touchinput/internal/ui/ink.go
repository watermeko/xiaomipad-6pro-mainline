package ui

import (
	"image"
	"image/color"
	"math"
	"os"
	"strconv"
	"time"
)

// inkDuration is how long a ripple takes; MYTOUCHINPUT_INK_MS stretches it so
// a screenshot can catch it.
var inkDuration = func() time.Duration {
	if v := os.Getenv("MYTOUCHINPUT_INK_MS"); v != "" {
		if ms, err := strconv.Atoi(v); err == nil && ms > 0 {
			return time.Duration(ms) * time.Millisecond
		}
	}
	return 480 * time.Millisecond
}()

// inkDebug logs every ripple frame, which is how the animation is verified
// without trying to photograph it.
var inkDebug = os.Getenv("MYTOUCHINPUT_INK_DEBUG") == "1"

// ripple is one Material ink reaction: a disc that grows from the touch point
// and fades out, clipped to the rounded shape it belongs to.
type ripple struct {
	box    keyBox
	corner int // corner radius of that shape
	x, y   int
	t0     time.Time
}

// addRipple starts the reaction for a shape that was just touched.  x and y are
// surface coordinates.
func (u *UI) addRipple(b keyBox, corner int, x, y float64) {
	u.ripples = append(u.ripples, ripple{
		box:    b,
		corner: corner,
		x:      int(x),
		y:      int(y),
		t0:     time.Now(),
	})
}

// expireRipples drops finished animations and reports whether any are left, so
// the caller knows to keep painting.
func (u *UI) expireRipples() bool {
	now := time.Now()
	live := u.ripples[:0]
	expired := false
	for _, r := range u.ripples {
		if now.Sub(r.t0) < inkDuration {
			live = append(live, r)
		} else {
			expired = true
		}
	}
	u.ripples = live
	if expired {
		// The last frame still had a little ink on it; restore the keys.
		u.composeDirty = true
	}
	return len(u.ripples) > 0 || expired
}

// drawRipples paints every ink reaction still in flight.
//
// A ripple has two parts, the way Material defines one: a state layer that
// tints the whole shape immediately, and the ink disc, which expands from the
// touch point until it just covers the shape and fades out as it arrives.
func (u *UI) drawRipples(img *image.RGBA) {
	now := time.Now()
	sc := u.scale
	for _, r := range u.ripples {
		p := float64(now.Sub(r.t0)) / float64(inkDuration)
		if p < 0 || p >= 1 {
			continue
		}
		box := image.Rect(
			r.box.x*sc, r.box.y*sc,
			(r.box.x+r.box.w)*sc, (r.box.y+r.box.h)*sc,
		)
		cx, cy := r.x*sc, r.y*sc
		corner := r.corner * sc

		// State layer: constant while the ripple lives, gone when it ends.
		fillRoundRect(img, box, corner, color.NRGBA{
			colInk.R, colInk.G, colInk.B, uint8(float64(0x14) * (1 - p)),
		})

		// Ink disc: decelerate, reaching the farthest corner exactly at p=1.
		far := math.Hypot(
			math.Max(math.Abs(float64(box.Min.X-cx)), math.Abs(float64(box.Max.X-cx))),
			math.Max(math.Abs(float64(box.Min.Y-cy)), math.Abs(float64(box.Max.Y-cy))),
		)
		ease := 1 - (1-p)*(1-p)
		disc := int(far * ease)
		alpha := uint8(float64(0x24) * (1 - p))
		if disc <= 0 || alpha == 0 {
			continue
		}
		if inkDebug {
			logf("ink p=%.2f disc=%d alpha=%d", p, disc, alpha)
		}
		paintDisc(img, box, corner, cx, cy, disc,
			color.NRGBA{colInk.R, colInk.G, colInk.B, alpha})
	}
}

// fillRoundRect fills a rounded rectangle, clipped to img.
func fillRoundRect(img *image.RGBA, box image.Rectangle, corner int, c color.NRGBA) {
	if c.A == 0 {
		return
	}
	for y := box.Min.Y; y < box.Max.Y; y++ {
		if y < img.Rect.Min.Y || y >= img.Rect.Max.Y {
			continue
		}
		inset := cornerInset(y-box.Min.Y, box.Dy(), corner)
		x0, x1 := box.Min.X+inset, box.Max.X-inset
		if x0 < img.Rect.Min.X {
			x0 = img.Rect.Min.X
		}
		if x1 > img.Rect.Max.X {
			x1 = img.Rect.Max.X
		}
		for x := x0; x < x1; x++ {
			blend(img, x, y, c)
		}
	}
}

// paintDisc blends a filled circle into img, clipped to the rounded rectangle
// of box so the ink never spills over a corner.
func paintDisc(img *image.RGBA, box image.Rectangle, corner, cx, cy, radius int, c color.NRGBA) {
	for y := box.Min.Y; y < box.Max.Y; y++ {
		if y < img.Rect.Min.Y || y >= img.Rect.Max.Y {
			continue
		}
		dy := y - cy
		if dy < -radius || dy > radius {
			continue
		}
		half := int(math.Sqrt(float64(radius*radius - dy*dy)))
		inset := cornerInset(y-box.Min.Y, box.Dy(), corner)
		x0, x1 := cx-half, cx+half
		if x0 < box.Min.X+inset {
			x0 = box.Min.X + inset
		}
		if x1 > box.Max.X-inset-1 {
			x1 = box.Max.X - inset - 1
		}
		if x0 < img.Rect.Min.X {
			x0 = img.Rect.Min.X
		}
		if x1 >= img.Rect.Max.X {
			x1 = img.Rect.Max.X - 1
		}
		for x := x0; x <= x1; x++ {
			blend(img, x, y, c)
		}
	}
}

// blend composites c over the pixel at x,y.
func blend(img *image.RGBA, x, y int, c color.NRGBA) {
	i := img.PixOffset(x, y)
	a := uint32(c.A)
	inv := 255 - a
	img.Pix[i+0] = uint8((uint32(c.R)*a + uint32(img.Pix[i+0])*inv) / 255)
	img.Pix[i+1] = uint8((uint32(c.G)*a + uint32(img.Pix[i+1])*inv) / 255)
	img.Pix[i+2] = uint8((uint32(c.B)*a + uint32(img.Pix[i+2])*inv) / 255)
	img.Pix[i+3] = 0xff
}
