import sys

from prepare_worker import verify_vendor, wrangler


if __name__ == "__main__":
    verify_vendor()
    wrangler("dev", *sys.argv[1:])
