"""batch — file-split preserved batch processor (boundless, no /mnt)"""
import os, json, argparse
from datetime import datetime
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

def process_file(src_path: str, out_base: str, max_size_mb: int = 50):
    from .epub import EpubSplitter
    from .models import A11yLogger
    name = Path(src_path).stem
    out_dir = os.path.join(out_base, f"{name}_split")
    logger = A11yLogger()
    splitter = EpubSplitter(max_size_bytes=max_size_mb*1024*1024, logger=logger)
    # file-splitting preserves original ZIP entries
    report = splitter.split(src_path, out_dir)
    return {"source": src_path, "success": True, "chunks": report.chunk_count, "out": out_dir, "warnings": report.warnings}

def main():
    ap = argparse.ArgumentParser(description="Batch EPUB splitter (file-preserving)")
    ap.add_argument("input", help="File or directory")
    ap.add_argument("-o", "--output", default="./output", help="Output base")
    ap.add_argument("-s", "--max-size", type=int, default=50, help="Max MB per chunk (Natural Reader 50)")
    ap.add_argument("-j", "--jobs", type=int, default=4)
    ap.add_argument("--exts", default="epub,pdf,docx", help="Extensions to process")
    args = ap.parse_args()
    exts = [e.strip().lower() for e in args.exts.split(",")]
    files = []
    p = Path(args.input)
    if p.is_file():
        files = [str(p)]
    elif p.is_dir():
        for root, _, fs in os.walk(p):
            for f in fs:
                if any(f.lower().endswith("."+e) for e in exts):
                    files.append(os.path.join(root, f))
    else:
        import glob
        for pat in args.input.split():
            files.extend(glob.glob(os.path.expanduser(pat)))

    print(f"Found {len(files)} files")
    results = []
    with ProcessPoolExecutor(max_workers=args.jobs) as executor:
        futures = {executor.submit(process_file, fp, args.output, args.max_size): fp for fp in files}
        for future in as_completed(futures):
            fp = futures[future]
            try:
                result = future.result()
                results.append(result)
                status = "OK" if result["success"] else "FAIL"
                print(f"[{status}] {os.path.basename(fp)} -> {result['chunks']} chunks")
            except Exception as e:
                print(f"[ERROR] {os.path.basename(fp)} -> {e}")
                results.append({"source": fp, "success": False, "error": str(e)})
    report_path = os.path.join(args.output, f"batch_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
    os.makedirs(args.output, exist_ok=True)
    with open(report_path, "w") as f:
        json.dump({"timestamp": datetime.now().isoformat(), "total_files": len(files), "successful": sum(1 for r in results if r.get("success")), "failed": sum(1 for r in results if not r.get("success")), "results": results}, f, indent=2)
    print(f"Batch report: {report_path}")

if __name__ == "__main__":
    main()
