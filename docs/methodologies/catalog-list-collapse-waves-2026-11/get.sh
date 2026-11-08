#!/bin/bash
# GET z allowlisty briefu; log do logs/net.log; wynik do raw/<nazwa>
url="$1"; out="$2"
case "$url" in
  https://substack.com/api/v1/*|https://smartflowproai.substack.com/api/v1/*|https://api.github.com/repos/x402-foundation/x402/issues/comments/*|https://docs.cdp.coinbase.com/*) ;;
  *) echo "DENY $url" | tee -a ~/nightq-1108-wi20/logs/net.log; exit 3;;
esac
code=$(curl -sS -X GET -A 'Mozilla/5.0' -o ~/nightq-1108-wi20/raw/"$out" -w '%{http_code}' --max-time 30 "$url")
echo "$(date -u +%FT%TZ) GET $url -> $code raw/$out" | tee -a ~/nightq-1108-wi20/logs/net.log
