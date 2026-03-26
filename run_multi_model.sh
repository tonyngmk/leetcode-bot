#!/bin/bash
# Launch workers with different models in parallel

WORKER_BASE=$1  # e.g., 110

# Model mapping: worker_n = model_(n % 4)
# w110, w111 -> glm-5 (2 workers)
# w112, w113 -> kimi-k2 (2 workers)
# w114, w115 -> minimax-2.5 (2 workers)
# w116, w117 -> minimax-2.7 (2 workers)

# Get next batch of slugs
SLUGS=$(python3 -c "
import json
with open('all_slugs.json') as f:
    all_slugs = json.load(f)
with open('solution_cache.json') as f:
    cached = set(json.load(f).keys())
remaining = [s for s in all_slugs if s not in cached]
print(','.join(remaining[:40]))
")

IFS=',' read -ra ARR <<< "$SLUGS"

# Launch 8 workers (4 models x 2 workers each)
for i in 0 1; do
    MODEL="glm-5"
    SLUG="${ARR[$i]},${ARR[$((i+8))]},${ARR[$((i+16))]},${ARR[$((i+24))]},${ARR[$((i+32))]}"
    nohup python3 run_batch.py w$((WORKER_BASE+i)) "$SLUG" --model $MODEL > /tmp/w$((WORKER_BASE+i)).log 2>&1 &
done

for i in 2 3; do
    MODEL="kimi-k2"
    SLUG="${ARR[$i]},${ARR[$((i+8))]},${ARR[$((i+16))]},${ARR[$((i+24))]},${ARR[$((i+32))]}"
    nohup python3 run_batch.py w$((WORKER_BASE+i)) "$SLUG" --model $MODEL > /tmp/w$((WORKER_BASE+i)).log 2>&1 &
done

for i in 4 5; do
    MODEL="minimax-2.5"
    SLUG="${ARR[$i]},${ARR[$((i+8))]},${ARR[$((i+16))]},${ARR[$((i+24))]},${ARR[$((i+32))]}"
    nohup python3 run_batch.py w$((WORKER_BASE+i)) "$SLUG" --model $MODEL > /tmp/w$((WORKER_BASE+i)).log 2>&1 &
done

for i in 6 7; do
    MODEL="minimax-2.7"
    SLUG="${ARR[$i]},${ARR[$((i+8))]},${ARR[$((i+16))]},${ARR[$((i+24))]},${ARR[$((i+32))]}"
    nohup python3 run_batch.py w$((WORKER_BASE+i)) "$SLUG" --model $MODEL > /tmp/w$((WORKER_BASE+i)).log 2>&1 &
done

echo "Launched workers $WORKER_BASE to $((WORKER_BASE+7)) with different models"
echo "Models: glm-5(2), kimi-k2(2), minimax-2.5(2), minimax-2.7(2)"