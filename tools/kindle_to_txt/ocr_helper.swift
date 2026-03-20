#!/usr/bin/env swift
// macOS Vision FrameworkでOCRを実行するヘルパースクリプト
// 使い方: swift ocr_helper.swift <image_path> [language]

import Foundation
import Vision
import AppKit

guard CommandLine.arguments.count >= 2 else {
    fputs("Usage: swift ocr_helper.swift <image_path> [language]\n", stderr)
    exit(1)
}

let imagePath = CommandLine.arguments[1]
let language = CommandLine.arguments.count >= 3 ? CommandLine.arguments[2] : "ja"
let languages = language.split(separator: ",").map { String($0) }

guard let image = NSImage(contentsOfFile: imagePath) else {
    fputs("Error: Cannot load image: \(imagePath)\n", stderr)
    exit(1)
}

guard let cgImage = image.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
    fputs("Error: Cannot convert image to CGImage\n", stderr)
    exit(1)
}

let request = VNRecognizeTextRequest()
request.recognitionLevel = .accurate
request.recognitionLanguages = languages
request.usesLanguageCorrection = true

let handler = VNImageRequestHandler(cgImage: cgImage, options: [:])

do {
    try handler.perform([request])
} catch {
    fputs("Error: OCR failed: \(error.localizedDescription)\n", stderr)
    exit(1)
}

guard let observations = request.results else {
    exit(0)
}

for observation in observations {
    if let topCandidate = observation.topCandidates(1).first {
        print(topCandidate.string)
    }
}
