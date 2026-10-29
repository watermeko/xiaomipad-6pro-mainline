// Raises the on-screen keyboard above application windows and keeps it out of
// the task switcher.  The window rule (kwinrulesrc) already forces position and
// size, but `keepabove` from a rule does not take effect on this compositor
// (measured: window.keepAbove stayed false), while a script can set it.
//
// Geometry is deliberately not touched here: KWin scripting has no way to
// construct a RectF (no Qt.rect, no QRectF), so the rule owns geometry.

var TARGET = "org.liuqin.Osk";

function raise(c) {
    if (!c || c.resourceClass !== TARGET) return;
    c.keepAbove = true;
    c.noBorder = true;
    c.skipTaskbar = true;
    c.skipSwitcher = true;
    c.onAllDesktops = true;
    print("DOCK raised " + c.resourceClass);
}

var clients = workspace.windowList ? workspace.windowList() : workspace.clientList();
for (var i = 0; i < clients.length; i++) raise(clients[i]);

if (workspace.windowAdded) workspace.windowAdded.connect(raise);
else if (workspace.clientAdded) workspace.clientAdded.connect(raise);
