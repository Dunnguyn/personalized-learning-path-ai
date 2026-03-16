Run this script from repo root after setting up the backend environment.
It seeds:
- sample concepts
- prerequisite edges
- knowledge_relations including related_to / used_in / part_of / example_of
- sample resources

python backend/scripts/seed_sample_data.py

Optional reset:
python backend/scripts/seed_sample_data.py --reset
