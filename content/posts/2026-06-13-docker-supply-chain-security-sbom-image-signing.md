---
title: "Docker Supply Chain Security — SBOM, Image Signing, and Verification"
description: "Secure your container supply chain in the homelab with SBOM generation via Syft, image signing with Cosign, vulnerability scanning via Grype, and Docker Content Trust enforcement. Real commands and workflows."
date: 2026-06-13T07:00:00-04:00
tags:
  - docker
  - security
  - linux
  - devops
  - homelab
keywords:
  - Docker container supply chain security homelab SBOM
  - Syft SBOM generation Docker images guide
  - Cosign container image signing verification homelab
  - Grype vulnerability scanning Docker container images
  - Docker Content Trust image signature verification
  - SLSA supply chain levels software artifact homelab
  - Docker image attestation in-toto provenance
summary: "Practical guide to securing your container supply chain in the homelab: generate SBOMs with Syft, sign images with Cosign, scan for vulnerabilities with Grype, and enforce Docker Content Trust."
canonical: "https://blog.gntech.me/posts/docker-supply-chain-security-sbom-image-signing/"
---

If you pull Docker images from Docker Hub, third-party registries, or even your own registry, you're trusting the entire chain from source code to your `docker pull`. The SolarWinds breach, the recent [Docker CVE-2026-31431](/posts/docker-cve-2026-31431-copy-fail-mitigation/), and the Arch Linux AUR malware incident (June 2026, 1500+ affected packages) all make one thing clear: supply chain attacks target infrastructure you thought was safe.

In a homelab, you might think "I'm not a target." You are — bots and automated scanners don't discriminate. The good news: securing your container supply chain with open-source tools is straightforward and lightweight. This guide covers the three pillars — SBOM generation, vulnerability scanning, image signing, and verification — using Syft, Grype, Cosign, and Docker Content Trust.

## Understanding the Container Supply Chain Security Landscape

Supply-chain levels for software artifacts (SLSA) defines a framework of security levels. For a homelab, achieving SLSA Level 2 is realistic: signed provenance, hosted builds, and verified sources. You don't need a full enterprise platform to get there.

In June 2026, Docker launched Hardened Images with Aikido vulnerability scanning, and the industry continues pushing toward transparency. An SBOM (Software Bill of Materials) is the foundation — it tells you exactly what packages are inside every layer of your image. With an SBOM in hand, you can scan for known vulnerabilities, verify the image was built by a trusted source, and detect tampering between build and deployment.

The tools we'll use fit into a single workflow:

```
Source → Build → SBOM (Syft) → Scan (Grype) → Sign (Cosign) → Deploy → Verify
```

Each step is optional and composable. Start with one, add the rest over time.

## Generating SBOMs with Syft

Syft from Anchore generates SBOMs from container images and filesystems. It supports SPDX, CycloneDX, and Syft's own JSON format.

### Installing Syft

```bash
curl -sSfL https://raw.githubusercontent.com/anchore/syft/main/install.sh | sh -s -- -b /usr/local/bin
```

Or via Docker:

```bash
docker run --rm -v /var/run/docker.sock:/var/run/docker.sock anchore/syft nginx:latest
```

### Generating SBOMs

Generate an SPDX SBOM for the image you use daily:

```bash
syft packages nginx:latest -o spdx-json=sbom.nginx.spdx.json
```

For CycloneDX format:

```bash
syft packages nginx:latest -o cyclonedx-json=sbom.nginx.cdx.json
```

### Comparing SBOMs Across Versions

Track how your images change over time:

```bash
syft packages myregistry.local/webapp:v1 -o spdx-json=sbom.v1.json
syft packages myregistry.local/webapp:v2 -o spdx-json=sbom.v2.json
diff <(jq '.artifacts[].name' sbom.v1.json | sort) <(jq '.artifacts[].name' sbom.v2.json | sort)
```

### Automating SBOM Generation

Use a systemd timer to generate SBOMs for your critical images weekly:

```ini
# /etc/systemd/system/syft-sbom.service
[Unit]
Description=Generate SBOM for nginx image
After=docker.service

[Service]
Type=oneshot
ExecStart=/usr/local/bin/syft packages nginx:latest -o spdx-json=/opt/sboms/nginx.spdx.json
```

```ini
# /etc/systemd/system/syft-sbom.timer
[Unit]
Description=Weekly SBOM generation

[Timer]
OnCalendar=weekly
Persistent=true

[Install]
WantedBy=timers.target
```

## Scanning for Vulnerabilities with Grype

Grype pairs with Syft natively — you can feed it an SBOM or scan an image directly.

### Installing Grype

```bash
curl -sSfL https://raw.githubusercontent.com/anchore/grype/main/install.sh | sh -s -- -b /usr/local/bin
```

### Scanning Images

Basic scan with severity summary:

```bash
grype nginx:latest
```

Show only vulnerabilities with a fix available:

```bash
grype --only-fixed nginx:latest
```

Fail the scan if any high-severity vulnerabilities exist (useful for CI):

```bash
grype --fail-on high nginx:latest
```

### Pipeline: SBOM → Scan

Generate an SBOM and scan it in one chain:

```bash
syft packages myapp:latest -o json | grype --fail-on medium
```

### Configuring Grype for Your Homelab

Create `~/.grype.yaml` to exclude false positives:

```yaml
# ~/.grype.yaml
ignore:
  - vulnerability: CVE-2023-XXXXX
    reason: "False positive in our base image"
    fix-state: not-fixed
severity:
  min-severity: medium
```

### Remediation Workflow

When Grype reports vulnerabilities:

1. Check if it's in the base image — update the base image tag
2. If it's in an added package — update the package version in your Dockerfile
3. If no fix exists — consider a distroless or hardened base image

## Signing Container Images with Cosign

Cosign from Sigstore is the de-facto tool for signing container images. It supports key-pair signing and keyless signing via OIDC.

### Installing Cosign

```bash
curl -O -L "https://github.com/sigstore/cosign/releases/latest/download/cosign-linux-amd64"
sudo mv cosign-linux-amd64 /usr/local/bin/cosign
sudo chmod +x /usr/local/bin/cosign
```

### Generating a Key Pair

```bash
cosign generate-key-pair
```

This creates `cosign.key` (private) and `cosign.pub` (public). Store the private key securely — consider using a password manager or `age` encryption.

### Signing an Image

Push your image to a registry, then sign:

```bash
docker push myregistry.local/myapp:latest
cosign sign --key cosign.key myregistry.local/myapp:latest
```

Cosign stores the signature as an additional manifest in the same registry under the tag `myregistry.local/myapp:sha256-<digest>.sig`.

### Verifying an Image

```bash
cosign verify --key cosign.pub myregistry.local/myapp:latest
```

The output includes the signature payload with the image digest. If the image has been tampered with, verification fails.

### Keyless Signing with OIDC

For CI pipelines on GitHub Actions or GitLab CI:

```bash
cosign sign myregistry.local/myapp:latest
```

Cosign uses the OIDC token from the CI environment (no key management needed). Verification for keyless signatures uses the Fulcio root:

```bash
cosign verify myregistry.local/myapp:latest
```

### Integrating with Docker Buildx

Use build attestations for provenance:

```bash
docker buildx build \
  --attest type=provenance,mode=max \
  --attest type=sbom \
  -t myregistry.local/myapp:latest \
  --push .
```

Then sign the attestation:

```bash
cosign attest --predicate sbom.spdx.json --key cosign.key myregistry.local/myapp:latest
```

### Storing Public Keys

Commit `cosign.pub` to your infrastructure Git repo:

```bash
git add cosign.pub
git commit -m "add cosign public key for image verification"
```

Then any team member can verify images from your registry.

## Enforcing Signed Images with Docker Content Trust

Docker Content Trust (DCT) uses Notary under the hood to enforce that only signed images can be pulled or pushed.

### Enable Docker Content Trust

```bash
export DOCKER_CONTENT_TRUST=1
```

With DCT enabled, every `docker push`, `docker pull`, and `docker build` will verify signatures.

### Pushing Signed Images

```bash
export DOCKER_CONTENT_TRUST=1
docker push myregistry.local/myapp:latest
```

Docker will prompt for the root key passphrase and the repository passphrase. Once configured, push succeeds only if the image is signed.

### Adding Delegated Signers

For teams or multiple machines:

```bash
docker trust signer add --key signer.pub team-lead myregistry.local/myapp
```

Then the signer can push signed images with their own key.

### Inspecting Trust Data

```bash
docker trust inspect myregistry.local/myapp --pretty
```

### Limitations in a Homelab

DCT works best with Docker Hub or a Notary-signer-enabled registry. For a simple Docker Registry v2, consider using Cosign exclusively, as DCT requires a Notary server alongside your registry.

## Building a Practical Homelab Pipeline

Combine everything into a Gitea Actions workflow:

```yaml
# .gitea/workflows/build-and-sign.yml
name: Build, Scan, and Sign
on: [push]

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Build image with provenance
        run: |
          docker buildx build \
            --attest type=provenance,mode=max \
            --attest type=sbom \
            -t ${{ secrets.REGISTRY }}/myapp:${{ github.sha }} \
            --push .

      - name: Scan with Grype
        run: |
          syft packages ${{ secrets.REGISTRY }}/myapp:${{ github.sha }} -o json | \
            grype --fail-on medium

      - name: Sign with Cosign
        run: |
          cosign sign --key <(echo "${{ secrets.COSIGN_KEY }}") \
            ${{ secrets.REGISTRY }}/myapp:${{ github.sha }}
```

For day-to-day use, add these aliases to your `.bashrc`:

```bash
alias scan='grype'
alias sbom='syft packages'
alias verify='cosign verify --key ~/.cosign/cosign.pub'
```

Run verification before deploying any image to production services in your homelab:

```bash
verify myregistry.local/myapp:latest && docker compose up -d
```

## Conclusion

Container supply chain security isn't just for enterprises. With Syft, Grype, and Cosign, you can generate SBOMs, scan for vulnerabilities, and sign your images — all with open-source tools and a few shell commands. Start with Syft and Grype (the biggest security gain with the least effort), then add Cosign when you want to guarantee image integrity.

The full workflow — SBOM → Scan → Sign → Verify — takes about 15 minutes to set up and protects every image you deploy.

### Resources

- [Syft GitHub](https://github.com/anchore/syft)
- [Grype GitHub](https://github.com/anchore/grype)
- [Cosign GitHub](https://github.com/sigstore/cosign)
- [SLSA Framework](https://slsa.dev/spec/v1.0/)
- [Docker Build Attestations](https://docs.docker.com/build/attestations/)
- [Docker Hardened Images](https://www.docker.com/blog/docker-hardened-images-enhanced-vulnerability-scanning-with-docker-and-aikido/)
