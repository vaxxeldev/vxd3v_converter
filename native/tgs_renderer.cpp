#include <rlottie.h>

#include <algorithm>
#include <array>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <iostream>
#include <limits>
#include <string>
#include <vector>

namespace {

constexpr std::size_t kMaxDimension = 2160;
constexpr std::size_t kMaxFrames = 360;

struct Tint {
    bool enabled{false};
    std::uint8_t red{0};
    std::uint8_t green{0};
    std::uint8_t blue{0};
};

bool parse_dimension(const char* value, std::size_t& output) {
    char* end = nullptr;
    const auto parsed = std::strtoul(value, &end, 10);
    if (end == value || *end != '\0' || parsed == 0 || parsed > kMaxDimension) {
        return false;
    }
    output = static_cast<std::size_t>(parsed);
    return true;
}

int hex_digit(char value) {
    if (value >= '0' && value <= '9') {
        return value - '0';
    }
    if (value >= 'a' && value <= 'f') {
        return value - 'a' + 10;
    }
    if (value >= 'A' && value <= 'F') {
        return value - 'A' + 10;
    }
    return -1;
}

bool parse_tint(const std::string& value, Tint& tint) {
    if (value == "none") {
        return true;
    }
    if (value.size() != 7 || value.front() != '#') {
        return false;
    }
    std::array<std::uint8_t*, 3> channels{&tint.red, &tint.green, &tint.blue};
    for (std::size_t index = 0; index < channels.size(); ++index) {
        const auto high = hex_digit(value[1 + index * 2]);
        const auto low = hex_digit(value[2 + index * 2]);
        if (high < 0 || low < 0) {
            return false;
        }
        *channels[index] = static_cast<std::uint8_t>((high << 4) | low);
    }
    tint.enabled = true;
    return true;
}

std::uint8_t unpremultiply(std::uint8_t channel, std::uint8_t alpha) {
    if (alpha == 0) {
        return 0;
    }
    const auto value = (static_cast<unsigned int>(channel) * 255U + alpha / 2U) / alpha;
    return static_cast<std::uint8_t>(std::min(value, 255U));
}

void to_straight_bgra(
    const std::vector<std::uint32_t>& premultiplied,
    std::vector<std::uint8_t>& straight,
    const Tint& tint
) {
    for (std::size_t index = 0; index < premultiplied.size(); ++index) {
        const auto pixel = premultiplied[index];
        const auto alpha = static_cast<std::uint8_t>((pixel >> 24U) & 0xFFU);
        auto red = static_cast<std::uint8_t>((pixel >> 16U) & 0xFFU);
        auto green = static_cast<std::uint8_t>((pixel >> 8U) & 0xFFU);
        auto blue = static_cast<std::uint8_t>(pixel & 0xFFU);

        if (tint.enabled && alpha != 0) {
            red = tint.red;
            green = tint.green;
            blue = tint.blue;
        } else {
            red = unpremultiply(red, alpha);
            green = unpremultiply(green, alpha);
            blue = unpremultiply(blue, alpha);
        }

        const auto offset = index * 4U;
        straight[offset] = blue;
        straight[offset + 1U] = green;
        straight[offset + 2U] = red;
        straight[offset + 3U] = alpha;
    }
}

}  // namespace

int main(int argc, char* argv[]) {
    if (argc != 5) {
        std::cerr << "usage: tgs-renderer <lottie.json> <width> <height> <#RRGGBB|none>\n";
        return 2;
    }

    std::size_t width = 0;
    std::size_t height = 0;
    Tint tint;
    if (!parse_dimension(argv[2], width) || !parse_dimension(argv[3], height)) {
        std::cerr << "invalid render dimensions\n";
        return 2;
    }
    if (!parse_tint(argv[4], tint)) {
        std::cerr << "invalid tint\n";
        return 2;
    }

    auto animation = rlottie::Animation::loadFromFile(argv[1], false);
    if (!animation) {
        std::cerr << "failed to load lottie animation\n";
        return 3;
    }
    const auto frame_count = animation->totalFrame();
    if (frame_count == 0 || frame_count > kMaxFrames) {
        std::cerr << "invalid animation frame count\n";
        return 4;
    }

    std::vector<std::uint32_t> premultiplied(width * height);
    std::vector<std::uint8_t> straight(width * height * 4U);
    rlottie::Surface surface(
        premultiplied.data(),
        width,
        height,
        width * sizeof(std::uint32_t)
    );

    for (std::size_t frame = 0; frame < frame_count; ++frame) {
        std::fill(premultiplied.begin(), premultiplied.end(), 0U);
        animation->renderSync(frame, surface, true);
        to_straight_bgra(premultiplied, straight, tint);
        if (std::fwrite(straight.data(), 1U, straight.size(), stdout) != straight.size()) {
            std::cerr << "failed to write rendered frame\n";
            return 5;
        }
    }

    if (std::fflush(stdout) != 0) {
        std::cerr << "failed to flush rendered frames\n";
        return 5;
    }
    return 0;
}
