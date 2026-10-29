# Where this came from

This directory used to be a git submodule pointing at
`https://github.com/watermeko/mytouchinput`.  It is now a plain directory inside
this repository so that the keyboard and the device payload it belongs to are
managed together; the standalone repository is kept as an archive and no longer
needs to be kept in sync.

It is a self-contained Go module: build it with

    cd device/touchinput && GOOS=linux GOARCH=arm64 go build -buildvcs=false -o /tmp/mytouchinput .
    # -buildvcs=false keeps the binary byte-identical between builds; otherwise
    # Go stamps the git revision into it and every build hashes differently.
    adb push /tmp/mytouchinput /var/tmp/ && adb shell sudo install -m755 /var/tmp/mytouchinput /usr/local/bin/mytouchinput
