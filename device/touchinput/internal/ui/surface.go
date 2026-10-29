package ui

import (
	"fmt"
	"image"
	"image/color"
	"image/draw"
	"os"
	"time"

	"golang.org/x/image/font"
	"golang.org/x/image/math/fixed"
	"golang.org/x/sys/unix"

	xdgshell "github.com/rajveermalviya/go-wayland/wayland/stable/xdg-shell"

	"github.com/watermeko/mytouchinput/internal/layout"
)

// Material Design 3 colour roles, dark scheme: a low-chroma neutral surface so
// the keyboard sits under any application, with the violet primary reserved for
// latched modifiers and the selected input method.
var (
	colBG       = color.NRGBA{0x1b, 0x19, 0x20, 0xff} // surface
	colKey      = color.NRGBA{0x2b, 0x29, 0x30, 0xff} // surfaceContainerHigh
	colMod      = color.NRGBA{0x36, 0x34, 0x3b, 0xff} // surfaceContainerHighest
	colActive   = color.NRGBA{0xd0, 0xbc, 0xff, 0xff} // primary
	colOnActive = color.NRGBA{0x38, 0x1e, 0x72, 0xff} // onPrimary
	colText     = color.NRGBA{0xe6, 0xe0, 0xe7, 0xff} // onSurface
	colTextDim  = color.NRGBA{0xca, 0xc4, 0xd0, 0xff} // onSurfaceVariant
	colInk      = color.NRGBA{0xe6, 0xe0, 0xe7, 0xff} // ripple, alpha animated
)

// Material metrics, in logical pixels.
const (
	keyRadius  = 9
	keyGap     = 5
	keyMargin  = 6
	toggleSide = 56
	toggleRad  = 14
)

// Run serves the keyboard until the process exits.  It starts collapsed: only
// the small toggle button is drawn, the rest of the surface is transparent and
// click-through, and tapping the button shows or hides the keys.
func (u *UI) Run() (err error) {
	defer func() {
		if err != nil {
			_ = u.ctx.Dispatch()
			_ = u.ctx.Dispatch()
			logf("run failed: %v", err)
		}
	}()
	if err := u.ensureSurface(); err != nil {
		return err
	}

	var paintTook func() time.Duration
	for {
		// Ink reactions animate, so keep repainting while any are alive.  This
		// is also what made the ripple look like a frozen halo: without it the
		// loop painted the frame the tap arrived in and then went quiet.
		if u.expireRipples() {
			u.dirty = true
		}
		if u.dirty {
			start := time.Now()
			if err := u.paint(); err != nil {
				return err
			}
			u.dirty = false
			d := start
			paintTook = func() time.Duration { return time.Since(d) }
			time.Sleep(12 * time.Millisecond)
		} else {
			time.Sleep(20 * time.Millisecond)
		}
		// Poll instead of chaining wl_surface.frame callbacks: the callback
		// proxies are never destroyed, and re-requesting one every iteration
		// killed the connection after a handful of frames.  Polling also keeps
		// events flowing while collapsed, so the toggle button stays tappable.
		rt := time.Now()
		if err := u.roundtrip(); err != nil {
			return fmt.Errorf("polling the compositor: %w", err)
		}
		if inkDebug && paintTook != nil {
			logf("frame paint=%v roundtrip=%v", paintTook().Round(time.Millisecond), time.Since(rt).Round(time.Millisecond))
			paintTook = nil
		}
	}
}

func (u *UI) ensureSurface() error {
	surface, err := u.compositor.CreateSurface()
	if err != nil {
		return err
	}
	u.surface = surface
	if u.scale > 1 {
		if err := surface.SetBufferScale(int32(u.scale)); err != nil {
			return fmt.Errorf("set_buffer_scale: %w", err)
		}
	}

	xdgSurface, err := u.wmBase.GetXdgSurface(surface)
	if err != nil {
		return err
	}
	u.xdgSurface = xdgSurface
	xdgSurface.SetConfigureHandler(func(ev xdgshell.SurfaceConfigureEvent) {
		u.configureSerial = ev.Serial
		if err := ackConfigure(xdgSurface, ev.Serial); err != nil {
			logf("ack_configure(%d): %v", ev.Serial, err)
		} else {
			logf("acked configure serial=%d", ev.Serial)
		}
		u.configured = true
		if err := setWindowGeometry(xdgSurface, 0, 0, int32(u.width), int32(u.height)); err != nil {
			logf("set_window_geometry: %v", err)
		} else {
			logf("set window geometry %dx%d", u.width, u.height)
		}
	})

	toplevel, err := xdgSurface.GetToplevel()
	if err != nil {
		return err
	}
	u.toplevel = toplevel
	logf("ids: surface=%d xdg_surface=%d toplevel=%d shm=%d comp=%d wm=%d seat=%d",
		surface.ID(), xdgSurface.ID(), toplevel.ID(), u.shm.ID(), u.compositor.ID(), u.wmBase.ID(), u.seat.ID())
	if err := setTitle(toplevel, u.cfg.Title); err != nil {
		return err
	}
	if err := setAppID(toplevel, u.cfg.AppID); err != nil {
		return err
	}
	// No min/max size: pinning it fights the KWin window rule that docks the
	// keyboard, and attaching a buffer that disagrees with the compositor's
	// configure gets rejected.

	logf("created surface + xdg_surface + toplevel")
	if os.Getenv("MYTOUCHINPUT_NO_WAIT") == "1" {
		logf("skipping the pre-configure commit/wait")
	} else {
		if err := surface.Commit(); err != nil {
			return err
		}
		for !u.configured {
			if err := u.ctx.Dispatch(); err != nil {
				return fmt.Errorf("waiting for configure: %w", err)
			}
		}
	}

	if err := u.createBuffers(); err != nil {
		logf("createBuffers: %v", err)
		return err
	}
	logf("created %d buffers", len(u.buffers))
	// Flush and surface any error the compositor raised about the pool/buffers
	// before we try to use them.
	if err := u.roundtrip(); err != nil {
		logf("roundtrip after buffers: %v", err)
		return err
	}
	logf("buffers accepted by the compositor")

	if os.Getenv("MYTOUCHINPUT_PROBE_ATTACH") == "1" {
		probe, err := u.compositor.CreateSurface()
		if err != nil {
			return err
		}
		logf("probe surface id=%d", probe.ID())
		if err := attachBuffer(probe, u.buffers[0], 0, 0); err != nil {
			logf("probe attach: %v", err)
			return err
		}
		logf("probe attach ok")
		if err := probe.Commit(); err != nil {
			logf("probe commit: %v", err)
			return err
		}
		logf("probe commit ok")
		if err := u.roundtrip(); err != nil {
			logf("probe roundtrip: %v", err)
			return err
		}
		logf("probe roundtrip ok -- shm attach works on a bare surface")
		os.Exit(0)
	}
	u.dirty = true
	return nil
}

func (u *UI) createBuffers() error {
	// The pool has to be page-aligned or the compositor's mmap of it fails.
	size := (u.stride*u.height*u.scale + 4095) &^ 4095
	for i := range u.buffers {
		fd, err := unix.MemfdCreate("mytouchinput-shm", unix.MFD_CLOEXEC)
		if err != nil {
			return fmt.Errorf("memfd: %w", err)
		}
		if err := unix.Ftruncate(fd, int64(size)); err != nil {
			unix.Close(fd)
			return err
		}
		data, err := unix.Mmap(fd, 0, size, unix.PROT_READ|unix.PROT_WRITE, unix.MAP_SHARED)
		if err != nil {
			unix.Close(fd)
			return err
		}

		pool, err := createPool(u.shm, fd, int32(size))
		if err != nil {
			unix.Close(fd)
			return err
		}
		u.pools = append(u.pools, pool)
		buf, err := createBuffer(pool, 0, int32(u.width*u.scale), int32(u.height*u.scale),
			int32(u.stride), shmFormatARGB8888)
		if err != nil {
			return err
		}
		u.buffers[i] = buf
		u.pixels = append(u.pixels, pixelTarget{data: data, fd: fd})
	}

	button, err := u.compositor.CreateRegion()
	if err != nil {
		return err
	}
	tr := u.toggleRect()
	if err := button.Add(int32(tr.x), int32(tr.y), int32(tr.w), int32(tr.h)); err != nil {
		return err
	}
	u.buttonRegion = button

	full, err := u.compositor.CreateRegion()
	if err != nil {
		return err
	}
	if err := full.Add(0, 0, int32(u.width), int32(u.height)); err != nil {
		return err
	}
	u.inputRegion = full
	return nil
}

type pixelTarget struct {
	data []byte
	fd   int
}

// paint renders the keyboard (or a fully transparent surface) and commits it.
func (u *UI) paint() (err error) {
	// A rejected request makes the compositor close the connection; the write
	// fails before the wl_display.error is read, so drain it for the report.
	defer func() {
		if err != nil {
			_ = u.ctx.Dispatch()
			_ = u.ctx.Dispatch()
			logf("paint failed: %v", err)
		}
	}()
	idx := u.nextBuffer
	u.nextBuffer = (u.nextBuffer + 1) % len(u.buffers)

	// The buffer is scale times the logical size; the compositor scales it back
	// down, which is what keeps the labels sharp.
	w, h := u.width*u.scale, u.height*u.scale
	if u.canvas == nil || u.canvas.Rect.Dx() != w || u.canvas.Rect.Dy() != h {
		u.canvas = image.NewRGBA(image.Rect(0, 0, w, h))
		u.base = image.NewRGBA(image.Rect(0, 0, w, h))
		u.composeDirty = true
	}
	img := u.canvas

	// Recompose the static frame only when it changed.  A ripple then only has
	// to restore the keys it touches, which is what keeps the animation smooth:
	// composing every key costs ~35 ms, which is far too slow for 60 fps.
	full := u.composeDirty || u.boxes == nil
	if full {
		u.boxes = u.layout()
		u.button = u.toggleRect()
		u.compose(u.base)
		u.composeDirty = false
	}
	boxes := u.rippleBoxes()
	if full {
		copy(img.Pix, u.base.Pix)
	} else {
		for _, r := range boxes {
			copyRows(u.base, img, r)
		}
	}
	u.drawRipples(img)

	// Every buffer has to hold the same content.  Writing only the buffer we
	// are about to attach leaves the other two showing whatever they had when
	// they were last used -- right after a state change that is the previous
	// state, so the panel flickered between expanded and collapsed for as long
	// as the ripple kept rotating buffers.
	if full {
		u.convertAll(img, 0, h, w)
	} else {
		for _, r := range boxes {
			u.convertAll(img, r.Min.Y, r.Max.Y, w)
		}
	}
	if inkDebug {
		logf("paint: expanded=%v boxes=%d full=%v", u.expanded, len(u.boxes), full)
	}

	if os.Getenv("MYTOUCHINPUT_NO_REGION") != "1" {
		// Collapsed: only the toggle button takes input, so taps fall through
		// to whatever is underneath.
		region := u.inputRegion
		if !u.expanded {
			region = u.buttonRegion
		}
		if err := u.surface.SetInputRegion(region); err != nil {
			return fmt.Errorf("set_input_region: %w", err)
		}
	}
	if os.Getenv("MYTOUCHINPUT_NO_ATTACH") != "1" {
		if err := attachBuffer(u.surface, u.buffers[idx], 0, 0); err != nil {
			return err
		}
	}
	if os.Getenv("MYTOUCHINPUT_NO_DAMAGE") != "1" {
		if err := u.surface.Damage(0, 0, int32(u.width), int32(u.height)); err != nil {
			return err
		}
	}
	if os.Getenv("MYTOUCHINPUT_NO_COMMIT") == "1" {
		return nil
	}
	return u.surface.Commit()
}

// compose draws everything that does not animate: the key grid and the toggle.
func (u *UI) compose(img *image.RGBA) {
	draw.Draw(img, img.Bounds(), image.Transparent, image.Point{}, draw.Src)
	if u.expanded {
		u.drawKeyboard(img)
	}
	u.drawToggle(img)
}

// rippleBoxes returns the buffer-space rectangles the live ripples touch.
func (u *UI) rippleBoxes() []image.Rectangle {
	sc := u.scale
	boxes := make([]image.Rectangle, 0, len(u.ripples))
	for _, r := range u.ripples {
		boxes = append(boxes, image.Rect(
			r.box.x*sc, r.box.y*sc,
			(r.box.x+r.box.w)*sc, (r.box.y+r.box.h)*sc,
		))
	}
	return boxes
}

// copyRows copies one rectangle from src into dst.
func copyRows(src, dst *image.RGBA, r image.Rectangle) {
	r = r.Intersect(dst.Rect)
	if r.Empty() {
		return
	}
	for y := r.Min.Y; y < r.Max.Y; y++ {
		srcRow := src.Pix[src.PixOffset(r.Min.X, y):src.PixOffset(r.Max.X, y)]
		dstRow := dst.Pix[dst.PixOffset(r.Min.X, y):dst.PixOffset(r.Max.X, y)]
		copy(dstRow, srcRow)
	}
}

// convertAll writes rows into every buffer, so whichever one is attached next
// shows the same frame.
func (u *UI) convertAll(img *image.RGBA, y0, y1, w int) {
	for _, target := range u.pixels {
		u.convertRows(img, target.data, y0, y1, w)
	}
}

// convertRows turns RGBA rows into the shm buffer's ARGB8888 little-endian
// order (which is B,G,R,A in memory).
func (u *UI) convertRows(img *image.RGBA, dst []byte, y0, y1, w int) {
	if y0 < 0 {
		y0 = 0
	}
	if y1 > u.height*u.scale {
		y1 = u.height * u.scale
	}
	for y := y0; y < y1; y++ {
		src := img.Pix[y*img.Stride : y*img.Stride+w*4]
		out := dst[y*u.stride : y*u.stride+w*4]
		for x := 0; x < w*4; x += 4 {
			out[x+0] = src[x+2]
			out[x+1] = src[x+1]
			out[x+2] = src[x+0]
			out[x+3] = src[x+3]
		}
	}
}

// drawToggle paints the show/hide button.
func (u *UI) drawToggle(img *image.RGBA) {
	b := u.toggleRect()
	bg, fg := colMod, colText
	if u.expanded {
		bg, fg = colActive, colOnActive
	}
	sc := u.scale
	u.roundedRect(img, b.x*sc, b.y*sc, b.w*sc, b.h*sc, toggleRad*sc, bg)
	iconKeyboard.blit(img, (b.x+b.w/2)*sc, (b.y+b.h/2)*sc, 28*sc, fg)
}

func (u *UI) drawKeyboard(img *image.RGBA) {
	draw.Draw(img, img.Bounds(), image.NewUniform(colBG), image.Point{}, draw.Src)

	sc := u.scale
	for _, b := range u.boxes {
		bg, fg := colKey, colText
		switch b.key.Act {
		case layout.Shift, layout.ShowSymbols, layout.ShowLetters, layout.ToggleIME:
			bg, fg = colMod, colTextDim
		}
		if b.key.Act == layout.Shift && u.shift {
			bg, fg = colActive, colOnActive
		}
		if b.key.Act == layout.ToggleIME && u.symbolsIME {
			bg, fg = colActive, colOnActive
		}
		if b.key.Label == "" {
			bg, fg = colMod, colTextDim // the space bar
		}
		u.roundedRect(img, b.x*sc, b.y*sc, b.w*sc, b.h*sc, keyRadius*sc, bg)
		u.drawKeyLabel(img, b, fg)
	}
}

// drawKeyLabel puts the Material icon or the character in the middle of a key.
func (u *UI) drawKeyLabel(img *image.RGBA, b keyBox, fg color.Color) {
	sc := u.scale
	cx := (b.x + b.w/2) * sc
	cy := (b.y + b.h/2) * sc
	switch {
	case b.key.Act == layout.Shift:
		iconShift.blit(img, cx, cy, 23*sc, fg.(color.NRGBA))
	case b.key.Code == 14: // backspace
		iconBackspace.blit(img, cx, cy, 26*sc, fg.(color.NRGBA))
	case b.key.Code == 28: // enter
		iconEnter.blit(img, cx, cy, 26*sc, fg.(color.NRGBA))
	case b.key.Label == "":
		// Space bar: a short dash, as Material keyboards draw it.
		w, h := 30*sc, 3*sc
		u.roundedRect(img, cx-w/2, cy-h/2, w, h, h/2, fg)
	default:
		txt := b.key.Label
		if u.shift && layout.IsLetter(b.key) {
			txt = layout.Uppercase(b.key)
		}
		u.centre(img, txt, b, fg)
	}
}

func (u *UI) text(img *image.RGBA, s string, x, y int, c color.Color) {
	d := &font.Drawer{
		Dst:  img,
		Src:  image.NewUniform(c),
		Face: u.face,
		Dot:  fixed.P(x, y),
	}
	d.DrawString(s)
}

func (u *UI) centre(img *image.RGBA, s string, b keyBox, c color.Color) {
	w := font.MeasureString(u.face, s).Ceil()
	metrics := u.face.Metrics()
	cx := (b.x+b.w/2)*u.scale - w/2
	cy := (b.y+b.h/2)*u.scale + (metrics.Ascent.Ceil()-metrics.Descent.Ceil())/2
	u.text(img, s, cx, cy, c)
}

func (u *UI) roundedRect(img *image.RGBA, x, y, w, h, r int, c color.Color) {
	for dy := 0; dy < h; dy++ {
		inset := cornerInset(dy, h, r)
		row := image.Rect(x+inset, y+dy, x+w-inset, y+dy+1)
		draw.Draw(img, row, image.NewUniform(c), image.Point{}, draw.Src)
	}
}

// cornerInset is how far a row has to be pulled in for a rounded corner.
func cornerInset(dy, h, r int) int {
	if r <= 0 || h < 2*r {
		return 0
	}
	var inset int
	switch {
	case dy < r:
		inset = r - roundInset(dy, r)
	case dy >= h-r:
		inset = r - roundInset(h-1-dy, r)
	}
	if inset < 0 {
		return 0
	}
	return inset
}

// roundInset returns how much of a row at distance d from the corner edge is
// still inside the rounded corner: the quarter circle's half-width, not its
// complement -- taking the complement carves the corners the wrong way round
// and leaves the keys joined by little bow-ties.
func roundInset(d, r int) int {
	if d <= 0 {
		return 0
	}
	if d >= r {
		return r
	}
	dy := float64(r - d)
	return int(round(sqrt(float64(r*r) - dy*dy)))
}

func sqrt(v float64) float64 {
	// Newton's method; avoids pulling in math for one call site.
	x := v
	if x <= 0 {
		return 0
	}
	for i := 0; i < 16; i++ {
		x = 0.5 * (x + v/x)
	}
	return x
}

func round(v float64) float64 {
	return float64(int(v + 0.5))
}

// press handles a tap at surface coordinates.
func (u *UI) press(x, y float64) {
	b := u.button
	if x >= float64(b.x) && x <= float64(b.x+b.w) &&
		y >= float64(b.y) && y <= float64(b.y+b.h) {
		u.addRipple(b, toggleRad, x, y)
		u.expanded = !u.expanded
		u.composeDirty = true
		u.dirty = true
		logf("toggle -> expanded=%v", u.expanded)
		return
	}
	if !u.expanded {
		return
	}
	for _, b := range u.boxes {
		if x < float64(b.x) || x > float64(b.x+b.w) ||
			y < float64(b.y) || y > float64(b.y+b.h) {
			continue
		}
		u.addRipple(b, keyRadius, x, y)
		u.activate(b.key)
		u.composeDirty = true
		u.dirty = true
		return
	}
}

func (u *UI) activate(k layout.Key) {
	switch k.Act {
	case layout.Shift:
		u.shift = !u.shift
	case layout.ShowSymbols:
		u.symbols = true
	case layout.ShowLetters:
		u.symbols = false
	case layout.ToggleIME:
		u.symbolsIME = !u.symbolsIME
	}
	u.on(k, u.shift)
}

// SetIME lets main report the current input method so the header can show it.
func (u *UI) SetIME(chinese bool) {
	if u.symbolsIME != chinese {
		u.symbolsIME = chinese
		u.composeDirty = true
		u.dirty = true
	}
}

// Redraw schedules a repaint.
func (u *UI) Redraw() {
	u.composeDirty = true
	u.dirty = true
}

var _ = xdgshell.WmBasePingEvent{}
var _ = unix.MFD_CLOEXEC

func logf(format string, args ...any) {
	fmt.Fprintf(os.Stderr, "ui: "+format+"\n", args...)
}
