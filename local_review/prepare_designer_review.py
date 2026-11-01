"""Root-only offline copy preparation; no server, SDK, simulation or baking."""
from pathlib import Path
import json
import designer_review


if __name__=='__main__':
    print(json.dumps(designer_review.prepare(Path(__file__).resolve().parent/'workspace'),ensure_ascii=False,indent=2))
