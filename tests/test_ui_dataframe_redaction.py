from pathlib import Path

import pandas as pd

from app.ui import redact_callback, scan_callback


def test_gradio_dataframe_rows_can_redact_txt(tmp_path: Path):
    source = tmp_path / "demo.txt"
    source.write_text(
        "Contact Alex at alex.morgan@example.com or 9876543210.",
        encoding="utf-8",
    )

    rows, report_data, scan_status = scan_callback(str(source), use_ai=False)
    assert report_data is not None, scan_status
    assert rows

    # Gradio versions can supply the editable table as a pandas DataFrame.
    table = pd.DataFrame(rows, columns=[
        "Approve", "Finding ID", "Category", "Matched text",
        "Source layer", "Location", "Reason",
    ])
    table["Approve"] = table["Finding ID"].apply(
        lambda finding_id: finding_id == rows[0][1]
    )

    output_path, status = redact_callback(str(source), table, report_data)
    assert output_path is not None, status
    redacted = Path(output_path).read_text(encoding="utf-8")
    approved_text = rows[0][3]
    assert approved_text not in redacted
    assert "[REDACTED]" in redacted
