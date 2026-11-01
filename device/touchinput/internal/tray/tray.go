// Package tray publishes the keyboard as a StatusNotifierItem.
//
// The keyboard used to draw its own show/hide button on its layer surface.
// That button is gone: the Plasma Mobile task panel hosts tray icons (the
// patch in plasma-mobile/source.json), so the keyboard registers an item there
// and its Activate method shows or hides the keys.
package tray

import (
	"fmt"
	"log"
	"os"
	"time"

	"github.com/godbus/dbus/v5"
	"github.com/godbus/dbus/v5/prop"
)

const (
	watcherBus   = "org.kde.StatusNotifierWatcher"
	watcherPath  = dbus.ObjectPath("/StatusNotifierWatcher")
	watcherIface = "org.kde.StatusNotifierWatcher"

	itemPath  = dbus.ObjectPath("/StatusNotifierItem")
	itemIface = "org.kde.StatusNotifierItem"

	// The panel draws whatever icon the theme has.  fcitx5's own item uses
	// "input-keyboard", so this one has to look different: two keyboard glyphs
	// side by side would be indistinguishable in the panel.
	iconName = "preferences-desktop-keyboard"
)

// Item is the published tray icon.
type Item struct {
	conn       *dbus.Conn
	name       string
	onActivate func()
}

// Publish registers the icon and returns once the watcher knows about it.  The
// callback runs on the D-Bus goroutine, so it must not block.
func Publish(title string, onActivate func()) (*Item, error) {
	conn, err := dbus.SessionBus()
	if err != nil {
		return nil, fmt.Errorf("connecting to the session bus: %w", err)
	}

	name := fmt.Sprintf("org.kde.StatusNotifierItem-%d-1", os.Getpid())
	reply, err := conn.RequestName(name, dbus.NameFlagDoNotQueue)
	if err != nil {
		return nil, fmt.Errorf("claiming %s: %w", name, err)
	}
	if reply != dbus.RequestNameReplyPrimaryOwner {
		return nil, fmt.Errorf("%s is already taken", name)
	}

	item := &Item{conn: conn, name: name, onActivate: onActivate}
	if err := conn.Export(item, itemPath, itemIface); err != nil {
		return nil, fmt.Errorf("exporting the item: %w", err)
	}

	// ItemIsMenu is false so that a tap calls Activate instead of asking for a
	// menu; Menu points at the conventional "no menu" path.
	_, err = prop.Export(conn, itemPath, map[string]map[string]*prop.Prop{
		itemIface: {
			"Category":          {Value: "ApplicationStatus", Writable: false, Emit: prop.EmitFalse},
			"Id":                {Value: "mytouchinput", Writable: false, Emit: prop.EmitFalse},
			"Title":             {Value: title, Writable: false, Emit: prop.EmitFalse},
			"Status":            {Value: "Active", Writable: false, Emit: prop.EmitFalse},
			"IconName":          {Value: iconName, Writable: false, Emit: prop.EmitFalse},
			"IconThemePath":     {Value: "", Writable: false, Emit: prop.EmitFalse},
			"ItemIsMenu":        {Value: false, Writable: false, Emit: prop.EmitFalse},
			"Menu":              {Value: dbus.ObjectPath("/NO_DBUSMENU"), Writable: false, Emit: prop.EmitFalse},
			"WindowId":          {Value: uint32(0), Writable: false, Emit: prop.EmitFalse},
			"OverlayIconName":   {Value: "", Writable: false, Emit: prop.EmitFalse},
			"AttentionIconName": {Value: "", Writable: false, Emit: prop.EmitFalse},
		},
	})
	if err != nil {
		return nil, fmt.Errorf("exporting the properties: %w", err)
	}

	// The watcher may still be starting when the session comes up, so keep
	// trying in the background rather than losing the icon.
	go item.register()

	return item, nil
}

// Name is the bus name the item owns.
func (i *Item) Name() string { return i.name }

func (i *Item) register() {
	watcher := i.conn.Object(watcherBus, watcherPath)
	for attempt := 0; attempt < 30; attempt++ {
		call := watcher.Call(watcherIface+".RegisterStatusNotifierItem", 0, i.name)
		if call.Err == nil {
			log.Printf("tray: registered %s", i.name)
			return
		}
		if attempt == 0 {
			log.Printf("tray: watcher not ready (%v), retrying", call.Err)
		}
		time.Sleep(time.Second)
	}
	log.Printf("tray: could not register %s with %s", i.name, watcherBus)
}

// Activate shows or hides the keyboard; the panel calls it on a tap.
func (i *Item) Activate(x, y int32) *dbus.Error {
	i.onActivate()
	return nil
}

// SecondaryActivate is the middle click.
func (i *Item) SecondaryActivate(x, y int32) *dbus.Error {
	i.onActivate()
	return nil
}

// ContextMenu is the right click; there is no menu, so it toggles too.
func (i *Item) ContextMenu(x, y int32) *dbus.Error {
	i.onActivate()
	return nil
}

// Scroll is part of the interface; the keyboard ignores it.
func (i *Item) Scroll(delta int32, orientation string) *dbus.Error {
	return nil
}

// Close releases the name and the exported object.
func (i *Item) Close() {
	_, _ = i.conn.ReleaseName(i.name)
}
