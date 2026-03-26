#!/bin/bash
# Batch 12 - launch when batch 11 finishes
nohup python3 run_batch.py w100 "odd-even-linked-list,longest-increasing-path-in-a-matrix,patching-array,verify-preorder-serialization-of-a-binary-tree,reconstruct-itinerary" > /tmp/w100.log 2>&1 &
nohup python3 run_batch.py w101 "largest-bst-subtree,increasing-triplet-subsequence,self-crossing,palindrome-pairs,house-robber-iii" > /tmp/w101.log 2>&1 &
nohup python3 run_batch.py w102 "counting-bits,nested-list-weight-sum,longest-substring-with-at-most-k-distinct-characters,flatten-nested-list-iterator,power-of-four" > /tmp/w102.log 2>&1 &
nohup python3 run_batch.py w103 "integer-break,reverse-string,reverse-vowels-of-a-string,moving-average-from-data-stream,top-k-frequent-elements" > /tmp/w103.log 2>&1 &
nohup python3 run_batch.py w104 "design-tic-tac-toe,intersection-of-two-arrays,intersection-of-two-arrays-ii,android-unlock-patterns,data-stream-as-disjoint-intervals" > /tmp/w104.log 2>&1 &
nohup python3 run_batch.py w105 "design-snake-game,russian-doll-envelopes,design-twitter,line-reflection,count-numbers-with-unique-digits" > /tmp/w105.log 2>&1 &
nohup python3 run_batch.py w106 "rearrange-string-k-distance-apart,logger-rate-limiter,sort-transformed-array,bomb-enemy,design-hit-counter" > /tmp/w106.log 2>&1 &
nohup python3 run_batch.py w107 "max-sum-of-rectangle-no-larger-than-k,nested-list-weight-sum-ii,water-and-jug-problem,find-leaves-of-binary-tree,valid-perfect-square" > /tmp/w107.log 2>&1 &
nohup python3 run_batch.py w108 "largest-divisible-subset,plus-one-linked-list,range-addition,sum-of-two-integers,super-pow" > /tmp/w108.log 2>&1 &
nohup python3 run_batch.py w109 "find-k-pairs-with-smallest-sums,guess-number-higher-or-lower,guess-number-higher-or-lower-ii,wiggle-subsequence,combination-sum-iv" > /tmp/w109.log 2>&1 &
echo "Batch 12 ready: w100-w109"
