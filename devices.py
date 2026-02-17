"""
Audio device enumeration utility.
Run: python list_devices.py

Lists all available audio input/output devices with their indices,
sample rates, and host APIs. Use this to find the correct device
indices for config.py.
"""

import sounddevice as sd


def list_devices():
    print("=" * 80)
    print("AUDIO DEVICES")
    print("=" * 80)

    devices = sd.query_devices()
    hostapis = sd.query_hostapis()

    # Print all devices grouped by host API
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

    # Print recommendations
    print("\n" + "=" * 80)
    print("RECOMMENDATIONS FOR CONFIG")
    print("=" * 80)

    print("\nFor MIC_DEVICE_INDEX:")
    print("  -> Use your microphone's index (marked [INPUT])")
    print(f"  -> Current default input: device [{sd.default.device[0]}]")

    print("\nFor LOOPBACK_DEVICE_INDEX:")
    print("  -> On Windows, look for WASAPI host API devices")
    print("  -> Find your speaker/headphone output device under WASAPI")
    print("  -> Some systems show a '(loopback)' variant — use that")
    print("  -> If no loopback visible, you may need to enable 'Stereo Mix'")
    print("     in Windows Sound Settings > Recording devices")
    print("  -> Or use a virtual audio cable (VB-Cable, etc.)")

    print(f"\nTo use WASAPI loopback, set the device index of your OUTPUT device")
    print(f"under the 'Windows WASAPI' host API section, and the code will")
    print(f"request loopback mode automatically.")


if __name__ == "__main__":
    list_devices()
