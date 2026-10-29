// The keyboard is one always-mapped toplevel: while the keys are hidden it
// paints only a button in the bottom-right corner and narrows its input region
// to that button, so taps outside it reach the application.
//
// A window rule pins its geometry and sets acceptfocus=false (tapping a key
// must not steal the focus the injected keys have to reach), but a rule cannot
// force keepAbove on this compositor, so this script raises the keyboard again
// whenever another window is activated or opened.

var TARGET = "org.liuqin.TouchInput";

function raiseKeyboard() {
    var ws = workspace.windowList ? workspace.windowList() : workspace.clientList();
    for (var i = 0; i < ws.length; i++) {
        var c = ws[i];
        if (!c || c.resourceClass !== TARGET) continue;
        c.keepAbove = true;
        c.noBorder = true;
        c.skipTaskbar = true;
        c.onAllDesktops = true;
    }
}

raiseKeyboard();

if (workspace.windowAdded) workspace.windowAdded.connect(raiseKeyboard);
else if (workspace.clientAdded) workspace.clientAdded.connect(raiseKeyboard);

if (workspace.windowActivated) workspace.windowActivated.connect(raiseKeyboard);
