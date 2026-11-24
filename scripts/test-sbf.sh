#!/usr/bin/env bash
set -euo pipefail

readonly expected_program_id="7wDzutwwr37nfxeMRydy5UEyREKho3Vjm8SxJgR4fzFy"
readonly deploy_keypair="target/deploy/zk_lorawan-keypair.json"
readonly fixture_keypair="tests/fixtures/integration-program-keypair.json"
readonly generated_wallet="$(pwd)/target/integration-wallet-keypair.json"

mkdir -p target/deploy

created_keypair=0
created_wallet=0
if [[ -f "${deploy_keypair}" ]]; then
    actual_program_id="$(solana-keygen pubkey "${deploy_keypair}")"
    if [[ "${actual_program_id}" != "${expected_program_id}" ]]; then
        echo "Refusing to overwrite ${deploy_keypair} (${actual_program_id})." >&2
        exit 1
    fi
else
    cp "${fixture_keypair}" "${deploy_keypair}"
    created_keypair=1
fi

if [[ -z "${ANCHOR_WALLET:-}" ]]; then
    solana-keygen new --no-bip39-passphrase --silent --outfile "${generated_wallet}"
    export ANCHOR_WALLET="${generated_wallet}"
    created_wallet=1
elif [[ ! -f "${ANCHOR_WALLET}" ]]; then
    echo "ANCHOR_WALLET does not exist: ${ANCHOR_WALLET}" >&2
    exit 1
fi

cleanup() {
    if [[ "${created_keypair}" -eq 1 ]]; then
        rm -f "${deploy_keypair}"
    fi
    if [[ "${created_wallet}" -eq 1 ]]; then
        rm -f "${generated_wallet}"
    fi
    if [[ -f Cargo.lock.bak ]]; then
        mv Cargo.lock.bak Cargo.lock
    fi
}
trap cleanup EXIT

cp Cargo.lock Cargo.lock.bak
cargo +1.83.0 build -p zk-lorawan-groth16 --release
# Solana 1.17's bundled Cargo predates lockfile v4. The v3 wire format is
# compatible with these locked entries; restore the original file on exit.
sed -i 's/^version = 4$/version = 3/' Cargo.lock
anchor build -- --features integration-test
anchor test --skip-build --provider.wallet "${ANCHOR_WALLET}"
