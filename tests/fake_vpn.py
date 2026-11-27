#!/usr/bin/env python3
"""Simulácia Cisco CLI `vpn` na testy (výzvy bez nového riadku, ako skutočné CLI).

FAKE_SCENARIO: ok | banner | badpw | untrusted | unknown | error | group | nouser | drop
FAKE_STATE: súbor so stavom (Connected/Disconnected)
"""
import os
import sys
import time

STATE = os.environ.get("FAKE_STATE", "/tmp/fake_vpn_state")
SC = os.environ.get("FAKE_SCENARIO", "ok")
HEADER = "Cisco Secure Client (version 5.1.13.177) .\n\nCopyright (c) 2004 - 2026 Cisco Systems, Inc.  All Rights Reserved.\n\n"


def out(s):
    sys.stdout.write(s)
    sys.stdout.flush()


def state():
    try:
        return open(STATE).read().strip() or "Disconnected"
    except OSError:
        return "Disconnected"


def set_state(s):
    with open(STATE, "w") as f:
        f.write(s)


def readline():
    line = sys.stdin.readline()
    if not line:
        sys.exit(0)
    return line.rstrip("\n")


def main():
    args = sys.argv[1:]
    if args == ["-v"]:
        out(HEADER)
        return
    if args == ["hosts"]:
        out(HEADER + "  >> notice: Ready to connect.\n[hosts]\n  > Firma B EAP+2FA\n  > Firma A\n")
        return
    if args == ["state"]:
        out(HEADER + f"  >> state: {state()}\n  >> state: {state()}\n  >> notice: Ready to connect.\n")
        return
    if args == ["stats"]:
        out(HEADER + f"  >> state: {state()}\n[ Connection Information ]\n\n    Tunnel Mode (IPv4):         Tunnel All Traffic\n"
            f"    Connection State:           {state()}\n    Duration:                   01:02:03\n\n"
            "[ Address Information ]\n\n    Client Address (IPv4):      10.20.30.40\n    Server Address:             198.51.100.7\n\n"
            "[ Bytes ]\n\n    Bytes Sent:                 4404019\n    Bytes Received:             19818086\n\n"
            "[ Transport Information ]\n\n    Protocol:                   IKEv2/IPsec NAT-T\n    Protocol Cipher:            AES_256_GCM\n\n"
            "[ Secured Routes (IPv4) ]\n\n    Network        Subnet\n    10.0.0.0       8\n    192.168.50.0   24\n\n")
        return
    if args == ["disconnect"]:
        set_state("Disconnected")
        out(HEADER + "  >> state: Disconnecting\n  >> state: Disconnected\n")
        return
    if args != ["-s"]:
        out("usage\n")
        return
    out(HEADER + "  >> notice: Ready to connect.\nVPN> ")
    while True:
        cmd = readline()
        if cmd == "exit":
            out("goodbye...\n")
            return
        if not cmd.startswith("connect "):
            out("VPN> ")
            continue
        host = cmd[8:]
        out(f"connect {host}\n  >> contacting host ({host}) for login information...\n  >> notice: Contacting {host}.\n")
        time.sleep(0.1)
        if SC == "error":
            out(f"  >> error: Unable to contact {host}.\n  >> error: Connection attempt has failed.\nVPN> ")
            continue
        if SC == "untrusted":
            out("\nSecurity threat! Untrusted VPN Server Blocked!\nCertificate is from an untrusted source.\n"
                "Change the setting that blocks untrusted connections? [y/n]: ")
            if readline() != "y":
                out("  >> error: Connection attempt has failed.\nVPN> ")
                continue
        if SC == "group":
            out("Group: [Default] ")
            readline()
        out("  >> Please enter your username and password.\n")
        if SC != "nouser":
            out("Username: [jnovak] ")
            readline()
        out("Password: ")
        pw = readline()
        if SC == "unknown":
            out("Answer the secret question:")
            time.sleep(60)
            return
        if SC == "badpw" or pw != os.environ.get("FAKE_PW", "tajne123456"):
            out("  >> Login failed.\n  >> Please enter your username and password.\nUsername: [jnovak] ")
            readline()
            out("Password: ")
            readline()
            out("  >> Login failed.\nVPN> ")
            continue
        if SC == "banner":
            out("  >> notice: Establishing VPN session...\n\nPristup len pre opravnenych pouzivatelov.\n"
                "Vsetka cinnost je zaznamenavana.\n\naccept? [y/n]: ")
            if readline() != "y":
                out("  >> state: Disconnected\nVPN> ")
                continue
        out("  >> state: Connecting\n  >> notice: Establishing VPN session...\n")
        time.sleep(0.2)
        set_state("Connected")
        out("  >> notice: Establishing VPN - Configuring system...\n  >> state: Connected\nVPN> ")
        if SC == "drop":
            time.sleep(0.5)
            set_state("Disconnected")
            out("  >> state: Disconnecting\n  >> notice: The VPN connection was terminated.\n  >> state: Disconnected\nVPN> ")


if __name__ == "__main__":
    main()
