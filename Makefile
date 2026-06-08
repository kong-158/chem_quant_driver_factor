.PHONY: install run clean

install:
	pip install -r requirements.txt

run:
	python main.py

clean:
	rm -rf data/processed/*.csv outputs/tables/*.csv outputs/figures/*.png outputs/logs/*.log src/__pycache__
