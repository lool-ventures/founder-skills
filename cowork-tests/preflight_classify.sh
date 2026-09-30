# Sourced by rerecord.sh (and its test). Classifies the cost pre-flight's outcome from the harness's
# MESSAGE, not its exit code.
#
# `record scenarios/ --dry-run --max-budget-usd <cap>` exits 2 for a budget refusal up to 3.10.0 and 1
# from 4.0.0 on, where 1 also means "a scenario did not load". The refusal message is the same on both:
# "... refused before spending ...". Every line the harness prints goes to stderr, and a scenario it
# could not load or refused is a line starting with "✗" (e.g. "✗ broken: <file>").
#
#   classify_preflight <exit code> <file holding the pre-flight's stderr>
# prints one of: ok | cost | load | load_and_cost  ("⚠ input error:" lines count as load, even at exit 0)
#   ok            exit 0
#   cost          the budget gate refused and every scenario loaded: raising the cap is the remedy
#   load          a scenario did not load or was refused, and no cost refusal: raising the cap cannot help
#   load_and_cost both: fix the scenario first; the cost figure may change once it loads
# A failure the classifier does not recognise is "load", never "cost": telling someone to raise a
# spending cap for a problem that is not about money is the failure this exists to prevent.
classify_preflight() {
  _rc="$1"
  _err="$2"
  # From 4.1.0 an input the real record would refuse (a bad path, or a negative tool assert the tier can
  # never violate) is listed as "⚠ input error:" and the dry-run still exits 0. The real record then
  # refuses it, so it is a load problem, never "ok" and never a cost problem.
  _input=0
  if grep -q "^⚠ input error:" "$_err" 2>/dev/null; then
    _input=1
  fi
  if [ "$_rc" -eq 0 ]; then
    if [ "$_input" -eq 1 ]; then
      echo load
    else
      echo ok
    fi
    return 0
  fi
  _cost=0
  _other="$_input"
  if grep -q "refused before spending" "$_err" 2>/dev/null; then
    _cost=1
  fi
  if grep -v "refused before spending" "$_err" 2>/dev/null | grep -q "✗"; then
    _other=1
  fi
  if [ "$_cost" -eq 1 ] && [ "$_other" -eq 1 ]; then
    echo load_and_cost
  elif [ "$_cost" -eq 1 ]; then
    echo cost
  else
    echo load
  fi
}
