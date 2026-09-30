# Sourced by rerecord.sh (and its test). Classifies the cost pre-flight's outcome from the harness's
# MESSAGE, not its exit code.
#
# `record scenarios/ --dry-run --max-budget-usd <cap>` exits 2 for a budget refusal up to 3.10.0 and 1
# from 4.0.0 on, where 1 also means "a scenario did not load". The refusal message is the same on both:
# "... refused before spending ...". Every line the harness prints goes to stderr, and a scenario it
# could not load or refused is a line starting with "✗" (e.g. "✗ broken: <file>").
#
#   classify_preflight <exit code> <file holding the pre-flight's stderr>
# prints one of: ok | cost | load | load_and_cost
#   ok            exit 0
#   cost          the budget gate refused and every scenario loaded: raising the cap is the remedy
#   load          a scenario did not load or was refused, and no cost refusal: raising the cap cannot help
#   load_and_cost both: fix the scenario first; the cost figure may change once it loads
# A failure the classifier does not recognise is "load", never "cost": telling someone to raise a
# spending cap for a problem that is not about money is the failure this exists to prevent.
classify_preflight() {
  _rc="$1"
  _err="$2"
  if [ "$_rc" -eq 0 ]; then
    echo ok
    return 0
  fi
  _cost=0
  _other=0
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
