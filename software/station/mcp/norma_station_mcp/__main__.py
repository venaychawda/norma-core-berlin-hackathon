import argparse
import sys


def main():
    parser = argparse.ArgumentParser(description="NormaCore Station MCP / HTTP server")
    parser.add_argument("--http", action="store_true", help="Start HTTP REST API instead of stdio MCP")
    parser.add_argument("--port", type=int, default=8080, help="HTTP server port (default: 8080)")
    parser.add_argument("--host", default="0.0.0.0", help="HTTP server bind address (default: 0.0.0.0)")
    args = parser.parse_args()

    if args.http:
        import uvicorn
        from norma_station_mcp.http_api import app

        print(f"Starting NormaCore HTTP API on {args.host}:{args.port}")
        uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    else:
        from norma_station_mcp.server import main as mcp_main
        mcp_main()


if __name__ == "__main__":
    main()
