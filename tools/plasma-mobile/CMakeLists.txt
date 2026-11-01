# SPDX-FileCopyrightText: 2026 watermeko
# SPDX-License-Identifier: MIT
#
# Standalone build of the patched Plasma Mobile task panel.
#
# The full plasma-mobile build wants KWin, KPipeWire, QCoro and a dozen other
# development packages; the task panel itself needs none of them, so this
# project builds the one containment from a plasma-mobile checkout:
#
#   cmake -S tools/plasma-mobile -B /tmp/taskpanel-build \
#         -DPLASMA_MOBILE_SOURCE=/home/watermeko/orca/plasma-mobile \
#         -DCMAKE_BUILD_TYPE=None
#   cmake --build /tmp/taskpanel-build -j8
#
# tools/deploy-liuqin-taskpanel.py runs that and installs the result on the
# tablet, together with the applet package its QML lives in.

cmake_minimum_required(VERSION 3.24)

project(plasma-mobile-taskpanel LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

if(NOT PLASMA_MOBILE_SOURCE)
    message(FATAL_ERROR "Set -DPLASMA_MOBILE_SOURCE=/path/to/plasma-mobile")
endif()

set(TASKPANEL_DIR ${PLASMA_MOBILE_SOURCE}/containments/taskpanel)

set(TASKPANEL_QML
    ${TASKPANEL_DIR}/qml/main.qml
    ${TASKPANEL_DIR}/qml/NavigationPanelComponent.qml
    ${TASKPANEL_DIR}/qml/GesturePanelComponent.qml
    ${TASKPANEL_DIR}/qml/TrayIconsComponent.qml
)

foreach(qml_file ${TASKPANEL_QML})
    if(NOT EXISTS ${qml_file})
        message(FATAL_ERROR "Missing ${qml_file} -- is PLASMA_MOBILE_SOURCE the patched checkout?")
    endif()
endforeach()

find_package(ECM REQUIRED NO_MODULE)
set(CMAKE_MODULE_PATH ${ECM_MODULE_PATH})

include(KDEInstallDirs)
include(KDECMakeSettings)

find_package(Qt6 REQUIRED COMPONENTS
    Core
    Gui
    Qml
    Quick
    DBus
    Sensors
)

find_package(Plasma REQUIRED)

find_package(KF6 REQUIRED COMPONENTS
    Config
    CoreAddons
    WindowSystem
)

# The task panel's own CMakeLists uses plasma_add_applet, which passes an empty
# RESOURCES keyword to ecm_target_qml_sources: fine with the ECM 6.22 that
# plasma-mobile targets, an error with the 6.24 this image ships, and its
# ecm_add_qml_module also refuses a target that already exists.  The macro only
# wraps add_library + a plugin factory, so declare the plugin here.
add_library(org.kde.plasma.mobile.taskpanel SHARED
    ${TASKPANEL_DIR}/taskpanel.cpp
    ${TASKPANEL_DIR}/statusnotifierhost.cpp
)

set_target_properties(org.kde.plasma.mobile.taskpanel PROPERTIES
    PREFIX ""
    AUTOMOC ON
    LIBRARY_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/plasma/applets"
)

target_link_libraries(org.kde.plasma.mobile.taskpanel PRIVATE
    Qt::Gui
    Qt::DBus
    Qt::Qml
    Qt::Quick
    Qt::Sensors
    Plasma::Plasma
    KF6::CoreAddons
    KF6::ConfigCore
    KF6::ConfigGui
    KF6::WindowSystem
)
