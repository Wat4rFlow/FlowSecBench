#!/bin/bash
# 生成实验室 PKI（RSA 2048，兼容 OpenVPN 2.3+）：CA / server / client
# 用法: gen-pki.sh <输出目录>
set -eu
OUT="${1:?usage: gen-pki.sh <dir>}"
mkdir -p "$OUT"
cd "$OUT"

# CA
openssl req -x509 -newkey rsa:2048 -nodes -days 3650 \
  -keyout ca.key -out ca.crt -subj "/CN=TSB Lab Root CA" 2>/dev/null

# server（EKU serverAuth，供 remote-cert-tls server 校验）
openssl req -newkey rsa:2048 -nodes -keyout server.key -out server.csr \
  -subj "/CN=tsb-lab-server" 2>/dev/null
cat > server.ext <<'EOF'
basicConstraints=CA:FALSE
keyUsage=digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
EOF
openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key -CAcreateserial \
  -days 825 -out server.crt -extfile server.ext 2>/dev/null

# client
openssl req -newkey rsa:2048 -nodes -keyout client.key -out client.csr \
  -subj "/CN=tsb-lab-client" 2>/dev/null
cat > client.ext <<'EOF'
basicConstraints=CA:FALSE
keyUsage=digitalSignature,keyEncipherment
extendedKeyUsage=clientAuth
EOF
openssl x509 -req -in client.csr -CA ca.crt -CAkey ca.key -CAcreateserial \
  -days 825 -out client.crt -extfile client.ext 2>/dev/null

chmod 600 ca.key server.key client.key
rm -f server.csr client.csr
echo "PKI OK: $(ls)"
