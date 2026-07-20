from .pipeline import main, parse_args

if __name__ == "__main__":
    args = parse_args()
    main(
        symbols=args.symbols,
        days=args.days,
        save_data=args.save_data,
        max_pages=args.max_pages,
        published_after=args.published_after,
        published_before=args.published_before,
        start_page=args.start_page,
    )
