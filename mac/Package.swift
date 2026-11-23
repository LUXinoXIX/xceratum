// swift-tools-version:5.9
import PackageDescription

let package = Package(
    name: "FiremnaVPN",
    platforms: [.macOS(.v13)],
    products: [
        .executable(name: "FiremnaVPN", targets: ["FiremnaVPN"]),
    ],
    targets: [
        // logika bez okien (Cisco CLI, profily, ini, certifikáty) – testuje sa v CI
        .target(name: "FiremnaVPNCore", path: "Sources/FiremnaVPNCore"),
        // aplikácia (SwiftUI, ikona v lište, Kľúčenka, Touch ID)
        .executableTarget(name: "FiremnaVPN", dependencies: ["FiremnaVPNCore"], path: "Sources/FiremnaVPN"),
        .testTarget(name: "FiremnaVPNCoreTests", dependencies: ["FiremnaVPNCore"], path: "Tests/FiremnaVPNCoreTests"),
    ]
)
