# Run this in a loop to start many clients
for i in {1..100}; do
  curl -N http://127.0.0.1:8000/events &
done
