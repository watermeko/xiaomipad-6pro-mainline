package ui

// wlr-layer-shell-unstable-v1, hand-encoded.
//
// The keyboard used to be an ordinary xdg_toplevel, which cannot work on this
// shell: Plasma Mobile's app launcher and its task switcher minimise every
// window before they show themselves, so the toggle button disappeared and
// could not be tapped, and the Plasma panels sit in KWin's TopLayer, above
// anything a window rule's keepAbove can reach.  A layer-shell surface on the
// overlay layer is not part of the window stack at all -- it cannot be
// minimised, it never appears in the task switcher, and it draws above panels,
// the launcher and fullscreen applications.
//
// The library this program is built on has no layer-shell bindings, and its
// string encoders are broken anyway (see bind.go), so the few requests needed
// here are written out by hand.

import (
	"fmt"

	"github.com/rajveermalviya/go-wayland/wayland/client"
)

// zwlr_layer_shell_v1 request opcodes.
const (
	layerShellGetLayerSurface = 0
)

// zwlr_layer_surface_v1 request opcodes.
const (
	layerSetSize                  = 0
	layerSetAnchor                = 1
	layerSetExclusiveZone         = 2
	layerSetMargin                = 3
	layerSetKeyboardInteractivity = 4
	layerAckConfigure             = 6
)

// zwlr_layer_surface_v1 events.
const (
	layerEventConfigure = 0
	layerEventClosed    = 1
)

// Layer values.
const (
	LayerBackground = 0
	LayerBottom     = 1
	LayerTop        = 2
	LayerOverlay    = 3
)

// Anchor bits.
const (
	AnchorTop    = 1
	AnchorBottom = 2
	AnchorLeft   = 4
	AnchorRight  = 8
)

// KeyboardInteractivity values.
const (
	KeyboardInteractivityNone      = 0
	KeyboardInteractivityOnDemand  = 1
	KeyboardInteractivityExclusive = 2
)

// layerProxy is a bare protocol object: the library only generates types for
// the interfaces it knows, and this one is not among them.
type layerProxy struct {
	client.BaseProxy
	handler func(opcode uint32, payload []byte)
}

func (p *layerProxy) Dispatch(opcode uint32, fd int, data []byte) {
	if p.handler != nil {
		p.handler(opcode, data)
	}
}

func intArg(v int32) []byte { return uintArg(uint32(v)) }

// bindLayerShell binds zwlr_layer_shell_v1 during the registry scan.
func (u *UI) bindLayerShell(ev client.RegistryGlobalEvent) {
	u.layerShell = &layerProxy{}
	u.ctx.Register(u.layerShell)
	if err := bindGlobal(u.registry, ev, 4, u.layerShell); err != nil {
		logf("bind zwlr_layer_shell_v1: %v", err)
		u.layerShell = nil
	}
}

// getLayerSurface sends zwlr_layer_shell_v1.get_layer_surface.
//
// The new object has to be registered before the request is written so that its
// id is the next one the compositor expects; the surface it is created for must
// already exist.
func (u *UI) getLayerSurface(surface *client.Surface, layer uint32, namespace string) (*layerProxy, error) {
	ls := &layerProxy{}
	u.ctx.Register(ls)

	payload := uintArg(ls.ID())
	payload = append(payload, uintArg(surface.ID())...)
	payload = append(payload, uintArg(0)...) // output: null, the compositor picks
	payload = append(payload, uintArg(layer)...)
	payload = append(payload, stringArg(namespace)...)
	if err := writeRequest(u.layerShell, layerShellGetLayerSurface, payload); err != nil {
		return nil, fmt.Errorf("get_layer_surface: %w", err)
	}
	return ls, nil
}

func (u *UI) layerSetSize(ls *layerProxy, w, h int) error {
	payload := append(intArg(int32(w)), intArg(int32(h))...)
	return writeRequest(ls, layerSetSize, payload)
}

func (u *UI) layerSetAnchor(ls *layerProxy, anchor uint32) error {
	return writeRequest(ls, layerSetAnchor, uintArg(anchor))
}

func (u *UI) layerSetExclusiveZone(ls *layerProxy, zone int32) error {
	return writeRequest(ls, layerSetExclusiveZone, intArg(zone))
}

func (u *UI) layerSetMargin(ls *layerProxy, top, right, bottom, left int32) error {
	payload := append(intArg(top), intArg(right)...)
	payload = append(payload, intArg(bottom)...)
	payload = append(payload, intArg(left)...)
	return writeRequest(ls, layerSetMargin, payload)
}

func (u *UI) layerSetKeyboardInteractivity(ls *layerProxy, mode uint32) error {
	return writeRequest(ls, layerSetKeyboardInteractivity, uintArg(mode))
}

func (u *UI) layerAckConfigure(ls *layerProxy, serial uint32) error {
	return writeRequest(ls, layerAckConfigure, uintArg(serial))
}
