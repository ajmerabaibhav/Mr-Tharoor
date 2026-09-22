// Record with Apple's voice processing turned on.
//
// The problem this solves, from first principles: signal-to-noise is decided
// at the microphone, and no amount of cleaning afterwards recovers detail the
// microphone never resolved. A first real recording measured 12 dB SNR, where
// the fricatives we need to judge -- s, z, th, f, v -- are the quietest sounds
// in speech and the first to disappear.
//
// Wispr Flow, macOS dictation and every other tool that works when you mumble
// are not using better hardware. They ask the operating system for the voice
// path instead of the raw one. On a Mac that is one line:
//
//     try inputNode.setVoiceProcessingEnabled(true)
//
// which turns on Apple's own echo cancellation, beamforming across the mic
// array, stationary and non-stationary noise suppression, and automatic gain.
// It runs on dedicated silicon, it is tuned by people with anechoic chambers,
// and it costs nothing. Writing our own spectral subtraction to compete with
// it would be a worse version of a solved problem.
//
// Python's sounddevice goes to CoreAudio's HAL directly and never sees any of
// it, which is why this small helper exists.
//
// Build:  swiftc -O -o voicecapture voicecapture.swift
// Use:    voicecapture <seconds> <output.wav> [--raw]

import AVFoundation
import Foundation

let arguments = CommandLine.arguments
guard arguments.count >= 3, let seconds = Double(arguments[1]) else {
    FileHandle.standardError.write(
        "usage: voicecapture <seconds> <output.wav> [--raw]\n".data(using: .utf8)!)
    exit(2)
}
let outputPath = arguments[2]
let wantsVoiceProcessing = !arguments.contains("--raw")

let engine = AVAudioEngine()
let input = engine.inputNode

if wantsVoiceProcessing {
    do {
        try input.setVoiceProcessingEnabled(true)
    } catch {
        // Not fatal: fall back to the raw path and say so, so a caller can
        // record the difference rather than silently getting worse audio.
        FileHandle.standardError.write(
            "warning: voice processing unavailable (\(error)), recording raw\n"
                .data(using: .utf8)!)
    }
}

// The input scope is the device's hardware format. The output scope can be
// stale for a moment after the default microphone route changes, and the input
// node cannot perform format conversion. Using that stale format makes
// installTap fail with "format mismatch" on multi-channel devices.
let hardwareFormat = input.inputFormat(forBus: 0)

// The phoneme model wants 16 kHz mono float. Convert once, here, rather than
// resampling later where a cheap resampler would undo the quality we gained.
guard
    let targetFormat = AVAudioFormat(
        commonFormat: .pcmFormatFloat32, sampleRate: 16000, channels: 1, interleaved: false),
    let converter = AVAudioConverter(from: hardwareFormat, to: targetFormat)
else {
    FileHandle.standardError.write("error: cannot build 16kHz converter\n".data(using: .utf8)!)
    exit(1)
}

var outputFile: AVAudioFile
do {
    outputFile = try AVAudioFile(
        forWriting: URL(fileURLWithPath: outputPath),
        settings: [
            AVFormatIDKey: kAudioFormatLinearPCM,
            AVLinearPCMBitDepthKey: 16,
            AVLinearPCMIsFloatKey: false,
            AVSampleRateKey: 16000.0,
            AVNumberOfChannelsKey: 1,
        ])
} catch {
    FileHandle.standardError.write("error: cannot open \(outputPath): \(error)\n".data(using: .utf8)!)
    exit(1)
}

let lock = NSLock()
var finished = false

input.installTap(onBus: 0, bufferSize: 4096, format: hardwareFormat) { buffer, _ in
    let ratio = targetFormat.sampleRate / hardwareFormat.sampleRate
    let capacity = AVAudioFrameCount(Double(buffer.frameLength) * ratio) + 64
    guard let converted = AVAudioPCMBuffer(pcmFormat: targetFormat, frameCapacity: capacity)
    else { return }

    var supplied = false
    var conversionError: NSError?
    converter.convert(to: converted, error: &conversionError) { _, status in
        if supplied {
            status.pointee = .noDataNow
            return nil
        }
        supplied = true
        status.pointee = .haveData
        return buffer
    }
    if conversionError != nil || converted.frameLength == 0 { return }

    lock.lock()
    defer { lock.unlock() }
    if !finished {
        try? outputFile.write(from: converted)
    }
}

do {
    try engine.start()
} catch {
    FileHandle.standardError.write("error: cannot start audio engine: \(error)\n".data(using: .utf8)!)
    exit(1)
}

// Report which path we actually got, so the caller never has to guess.
print(wantsVoiceProcessing && input.isVoiceProcessingEnabled ? "voice-processing" : "raw")
fflush(stdout)

Thread.sleep(forTimeInterval: seconds)

lock.lock()
finished = true
lock.unlock()

input.removeTap(onBus: 0)
engine.stop()
exit(0)
