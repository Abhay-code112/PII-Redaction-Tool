"""Command line entry point:  python redact.py input.docx -o output.docx"""
import argparse
import sys
import time

from pii_redactor import Policy, Redactor


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Replace PII in a .docx with consistent fake values.")
    ap.add_argument("input")
    ap.add_argument("-o", "--output", default="output/redacted.docx")
    ap.add_argument("--audit", help="write a JSON log of every replacement (contains the ORIGINAL PII)")
    ap.add_argument("--mode", choices=["regex", "ner", "hybrid"], default="hybrid")
    ap.add_argument("--seed", default="pii-redactor", help="same seed -> same fakes")
    ap.add_argument("--skip", nargs="*", default=[], metavar="LABEL", help="e.g. --skip URL ORG")
    ap.add_argument("--no-images", action="store_true", help="skip OCR redaction of pictures inside the document")
    args = ap.parse_args(argv)

    t0 = time.time()
    red = Redactor(Policy(mode=args.mode, skip_labels=frozenset(args.skip), seed=args.seed,
                        images=not args.no_images))
    report = red.redact_file(args.input, args.output, args.audit)
    print(f"wrote {args.output} in {time.time() - t0:.1f}s")
    for label, n in report.counts.most_common():
        print(f"  {label:<12}{n}")
    print("cleaning:", dict(report.cleaning))
    if report.images:
        hit = [r for r in report.images if r.get("regions") or r.get("faces") or r.get("qr")]
        print(f"images: {len(report.images)} scanned, {len(hit)} redacted "
              f"({sum(r.get('regions', 0) for r in hit)} text regions, {sum(r.get('faces', 0) for r in hit)} faces, "
              f"{sum(r.get('qr', 0) for r in hit)} QR codes)")
    for w in report.warnings:
        print("warning:", w)
    return 0


if __name__ == "__main__":
    sys.exit(main())
