#!/usr/bin/env swift
// Captures the main display and saves as JPEG to the specified path
// Usage: screenshot <output-path.jpg>

import Foundation
import ScreenCaptureKit
import CoreGraphics
import AppKit

guard CommandLine.arguments.count > 1 else {
    fputs("Usage: screenshot <output-path.jpg>\n", stderr)
    exit(1)
}

let outputPath = CommandLine.arguments[1]
let semaphore = DispatchSemaphore(value: 0)
var exitCode: Int32 = 1

SCShareableContent.getWithCompletionHandler { content, error in
    guard let content = content, let display = content.displays.first else {
        fputs("Error getting display: \(error?.localizedDescription ?? "unknown")\n", stderr)
        semaphore.signal()
        return
    }

    let filter = SCContentFilter(display: display, excludingWindows: [])
    let config = SCStreamConfiguration()
    config.width = 1920
    config.height = 1080
    config.pixelFormat = kCVPixelFormatType_32BGRA
    config.showsCursor = false

    SCScreenshotManager.captureImage(contentFilter: filter, configuration: config) { image, error in
        guard let image = image else {
            fputs("Capture error: \(error?.localizedDescription ?? "unknown")\n", stderr)
            semaphore.signal()
            return
        }

        let nsImage = NSImage(cgImage: image, size: NSSize(width: image.width, height: image.height))
        guard let tiffData = nsImage.tiffRepresentation,
              let bitmap = NSBitmapImageRep(data: tiffData),
              let jpegData = bitmap.representation(using: .jpeg, properties: [.compressionFactor: 0.6]) else {
            fputs("Failed to encode JPEG\n", stderr)
            semaphore.signal()
            return
        }

        do {
            try jpegData.write(to: URL(fileURLWithPath: outputPath))
            print("OK:\(jpegData.count)")
            exitCode = 0
        } catch {
            fputs("Write error: \(error.localizedDescription)\n", stderr)
        }
        semaphore.signal()
    }
}

semaphore.wait()
exit(exitCode)
