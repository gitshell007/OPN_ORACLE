import Foundation
import Vision

guard CommandLine.arguments.count == 2 else {
    FileHandle.standardError.write(
        Data("usage: vision_ocr.swift IMAGE_PATH\n".utf8)
    )
    exit(64)
}

let imageURL = URL(fileURLWithPath: CommandLine.arguments[1])
let request = VNRecognizeTextRequest()
request.recognitionLevel = .accurate
request.usesLanguageCorrection = true
request.recognitionLanguages = ["es-ES", "en-US"]

let handler = VNImageRequestHandler(url: imageURL, options: [:])
do {
    try handler.perform([request])
    let lines = (request.results ?? []).compactMap { observation in
        observation.topCandidates(1).first?.string
    }
    let output: [String: Any] = [
        "line_count": lines.count,
        "lines": lines,
    ]
    let data = try JSONSerialization.data(withJSONObject: output, options: [.sortedKeys])
    FileHandle.standardOutput.write(data)
    FileHandle.standardOutput.write(Data("\n".utf8))
} catch {
    FileHandle.standardError.write(Data("vision_ocr_failed: \(error)\n".utf8))
    exit(1)
}
