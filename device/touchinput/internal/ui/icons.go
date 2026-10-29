package ui

import (
	"image"
	"image/color"
	"math"
)

// The special keys draw Material Design icons instead of font glyphs: the Go
// and DejaVu faces disagree on how ⇧, ⌫ and ⏎ look, and at keyboard sizes the
// results were uneven.  Each icon is described as primitives on a 24x24 grid,
// rasterised once into a supersampled coverage mask, and then box-filtered down
// to the size it is drawn at, which is where the anti-aliasing comes from.

const (
	iconGrid    = 24
	iconSamples = 4 // supersampling per grid unit
)

// iconMask holds coverage for one icon: 0 is empty, 255 is fully covered.
type iconMask struct {
	n   int
	cov []uint8
}

// paint fills the mask for fn, which reports whether a point on the 24x24 grid
// is inside the shape.
func newIconMask(fn func(x, y float64) bool) *iconMask {
	n := iconGrid * iconSamples
	m := &iconMask{n: n, cov: make([]uint8, n*n)}
	scale := 1 / float64(iconSamples)
	for py := 0; py < n; py++ {
		y := (float64(py) + 0.5) * scale
		for px := 0; px < n; px++ {
			x := (float64(px) + 0.5) * scale
			if fn(x, y) {
				m.cov[py*n+px] = 255
			}
		}
	}
	return m
}

// triangle reports whether p is inside the triangle abc.
func inTriangle(px, py float64, ax, ay, bx, by, cx, cy float64) bool {
	d1 := (px-bx)*(ay-by) - (ax-bx)*(py-by)
	d2 := (px-cx)*(by-cy) - (bx-cx)*(py-cy)
	d3 := (px-ax)*(cy-ay) - (cx-ax)*(py-ay)
	hasNeg := d1 < 0 || d2 < 0 || d3 < 0
	hasPos := d1 > 0 || d2 > 0 || d3 > 0
	return !(hasNeg && hasPos)
}

// inSegment reports whether p is within w/2 of the segment ab, with round ends.
func inSegment(px, py, ax, ay, bx, by, w float64) bool {
	dx, dy := bx-ax, by-ay
	l := dx*dx + dy*dy
	t := 0.0
	if l > 0 {
		t = ((px-ax)*dx + (py-ay)*dy) / l
		t = math.Max(0, math.Min(1, t))
	}
	cx, cy := ax+t*dx, ay+t*dy
	return math.Hypot(px-cx, py-cy) <= w/2
}

func inRect(px, py, x0, y0, x1, y1 float64) bool {
	return px >= x0 && px <= x1 && py >= y0 && py <= y1
}

// inRoundRect is inRect with rounded corners of radius r.
func inRoundRect(px, py, x0, y0, x1, y1, r float64) bool {
	if px < x0 || px > x1 || py < y0 || py > y1 {
		return false
	}
	cx := math.Max(x0+r, math.Min(px, x1-r))
	cy := math.Max(y0+r, math.Min(py, y1-r))
	return math.Hypot(px-cx, py-cy) <= r
}

var (
	// Shift: an upward arrow, the same silhouette as Material's shift key.
	iconShift = newIconMask(func(x, y float64) bool {
		return inTriangle(x, y, 12, 3.5, 20.5, 12.5, 3.5, 12.5) ||
			inRect(x, y, 9.75, 11.5, 14.25, 20.5)
	})

	// Backspace: the Material pentagon with a cross inside, stroked.
	iconBackspace = newIconMask(func(x, y float64) bool {
		const w = 2.4
		return inSegment(x, y, 9.5, 4.5, 21, 4.5, w) ||
			inSegment(x, y, 21, 4.5, 21, 19.5, w) ||
			inSegment(x, y, 21, 19.5, 9.5, 19.5, w) ||
			inSegment(x, y, 9.5, 19.5, 2.5, 12, w) ||
			inSegment(x, y, 2.5, 12, 9.5, 4.5, w) ||
			inSegment(x, y, 12, 9, 17.5, 15, w*0.85) ||
			inSegment(x, y, 17.5, 9, 12, 15, w*0.85)
	})

	// Enter: Material's return arrow, a hook ending in a left arrowhead.
	iconEnter = newIconMask(func(x, y float64) bool {
		const w = 2.4
		return inSegment(x, y, 19.5, 4.5, 19.5, 16.5, w) ||
			inSegment(x, y, 19.5, 16.5, 9.5, 16.5, w) ||
			inTriangle(x, y, 4, 16.5, 11, 11, 11, 22)
	})

	// Keyboard: the glyph shown on the toggle button -- a rounded frame with
	// key dots and a space bar.
	iconKeyboard = newIconMask(func(x, y float64) bool {
		const w = 2.2
		if inRoundRect(x, y, 2.5, 6.5, 21.5, 17.5, 2.6) &&
			!inRoundRect(x, y, 4.8, 8.8, 19.2, 15.2, 1.4) {
			return true
		}
		// three rows of dots
		for row := 0; row < 2; row++ {
			for col := 0; col < 4; col++ {
				cx := 7.0 + float64(col)*3.2
				cy := 10.4 + float64(row)*2.6
				if math.Hypot(x-cx, y-cy) <= 0.85 {
					return true
				}
			}
		}
		// space bar
		return inRect(x, y, 8.2, 14.0, 15.8, 15.0) || w < 0
	})
)

// blit draws the mask into img, scaled to size and centred on centre.
func (m *iconMask) blit(img *image.RGBA, cx, cy, size int, col color.NRGBA) {
	if size <= 0 {
		return
	}
	x0, y0 := cx-size/2, cy-size/2
	step := float64(m.n) / float64(size)
	for dy := 0; dy < size; dy++ {
		sy0 := int(float64(dy) * step)
		sy1 := int(float64(dy+1) * step)
		if sy1 <= sy0 {
			sy1 = sy0 + 1
		}
		for dx := 0; dx < size; dx++ {
			sx0 := int(float64(dx) * step)
			sx1 := int(float64(dx+1) * step)
			if sx1 <= sx0 {
				sx1 = sx0 + 1
			}
			sum, n := 0, 0
			for sy := sy0; sy < sy1 && sy < m.n; sy++ {
				row := sy * m.n
				for sx := sx0; sx < sx1 && sx < m.n; sx++ {
					sum += int(m.cov[row+sx])
					n++
				}
			}
			if n == 0 || sum == 0 {
				continue
			}
			c := col
			c.A = uint8(int(c.A) * sum / (n * 255))
			if c.A == 0 {
				continue
			}
			blend(img, x0+dx, y0+dy, c)
		}
	}
}
