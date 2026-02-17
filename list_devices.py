"""
List all audio devices on your system.
Run:  python list_devices.py
"""

import sounddevice as sd


def list_devices():
    print("=" * 80)
    print("AUDIO DEVICES")
    print("=" * 80)

    devices = sd.query_devices()
    hostapis = sd.query_hostapis()

    for api_idx, api in enumerate(hostapis):
        api_name = api["name"]
        api_devices = api["devices"]

        print(f"\n--- Host API: {api_name} (index {api_idx}) ---")

        for dev_idx in api_devices:
            dev = devices[dev_idx]
            dev_name = dev["name"]
            max_in = dev["max_input_channels"]
            max_out = dev["max_output_channels"]
            default_sr = dev["default_samplerate"]

            direction = ""
            if max_in > 0 and max_out > 0:
                direction = "[IN/OUT]"
            elif max_in > 0:
                direction = "[INPUT] "
            elif max_out > 0:
                direction = "[OUTPUT]"

            marker = ""
            if dev_idx == sd.default.device[0]:
                marker += " << DEFAULT INPUT"
            if dev_idx == sd.default.device[1]:
                marker += " << DEFAULT OUTPUT"

            print(
                f"  [{dev_idx:3d}] {direction} {dev_name:<50s} "
                f"(in:{max_in} out:{max_out} sr:{default_sr:.0f}){marker}"
            )

    print("\n" + "=" * 80)
    print("RECOMMENDATIONS FOR CONFIG")
    print("=" * 80)

    print("\nFor MIC_DEVICE_INDEX:")
    print("  -> Use your microphone's index (marked [INPUT])")
    print(f"  -> Current default input: device [{sd.default.device[0]}]")

    print("\nFor LOOPBACK_DEVICE_INDEX:")
    print("  -> Device [28] Stereo Mix is recommended if available")
    print("  -> Or use a WASAPI output device with LOOPBACK_IS_INPUT_DEVICE=False")


if __name__ == "__main__":
    list_devices()
