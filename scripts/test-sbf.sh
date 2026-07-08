#!/usr/bin/env bash
set -euo pipefail

readonly expected_program_id="7wDzutwwr37nfxeMRydy5UEyREKho3Vjm8SxJgR4fzFy"
readonly deploy_keypair="target/deploy/zk_lorawan-keypair.json"
readonly fixture_keypair="tests/fixtures/integration-program-keypair.json"

mkdir -p target/deploy

created_keypair=0
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

cleanup() {
    if [[ "${created_keypair}" -eq 1 ]]; then
        rm -f "${deploy_keypair}"
    fi
}
trap cleanup EXIT

anchor build -- --features integration-test
anchor test --skip-build
