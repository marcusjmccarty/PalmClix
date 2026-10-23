// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "PalmClixMac",
    platforms: [.macOS(.v12)],
    products: [.executable(name: "PalmClixMac", targets: ["PalmClixMac"])],
    targets: [
        .executableTarget(
            name: "PalmClixMac",
            path: "Sources/PalmClix",
            resources: [.copy("Assets"), .copy("Backend")]
        )
    ]
)
