# generate python files from proto:
# python -m grpc_tools.protoc \
#   -Iproto \
#   --python_out=proto \
#   --grpc_python_out=proto \
#   proto/raft.proto proto/user_cart.proto proto/inventory.proto
