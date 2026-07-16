// Generated fixture. Shape matches Ticket 106 report_data.json; no browser calculations.
export const REPORT_DATA = {
  "version": 1,
  "generated_at": "2026-07-15T14:10:00Z",
  "run_id": "crawl_whiskipedia_demo",
  "run_label": "Whiskipedia \u00b7 completed snapshot",
  "embedding_model": "fixture-embedding-model",
  "projection": {
    "method": "PCA fixture",
    "dims": 2,
    "seed": 42
  },
  "thresholds": {
    "similarity": 0.85
  },
  "summary": {
    "embedded": 10,
    "overlap_pairs": 5,
    "clusters": 3,
    "duplicate_pages": 2,
    "thin_content_pages": 1,
    "threshold": 0.85
  },
  "pages": [
    {
      "url": "https://whiskipedia.com/",
      "cluster_id": "c-scotland",
      "coords": [
        -0.8,
        0.3
      ],
      "risk": "overlap",
      "url_class": "normal",
      "variant_kind": null,
      "word_count": 600,
      "main_text_words": 580,
      "main_text_chars": 2900,
      "signature_words": 570,
      "signature_chars": 2850,
      "max_similarity": 0.97,
      "centroid_similarity": 0.91,
      "off_topic": false,
      "excluded": null
    },
    {
      "url": "https://whiskipedia.com/scotland/",
      "cluster_id": "c-scotland",
      "coords": [
        -0.35,
        0.75
      ],
      "risk": "duplicate",
      "url_class": "normal",
      "variant_kind": null,
      "word_count": 420,
      "main_text_words": 400,
      "main_text_chars": 2000,
      "signature_words": 390,
      "signature_chars": 1950,
      "max_similarity": 0.952,
      "centroid_similarity": 0.882,
      "off_topic": false,
      "excluded": null
    },
    {
      "url": "https://whiskipedia.com/scotland/islay/",
      "cluster_id": "c-scotland",
      "coords": [
        -0.12,
        0.56
      ],
      "risk": "overlap",
      "url_class": "normal",
      "variant_kind": null,
      "word_count": 279,
      "main_text_words": 259,
      "main_text_chars": 1295,
      "signature_words": 249,
      "signature_chars": 1245,
      "max_similarity": 0.934,
      "centroid_similarity": 0.854,
      "off_topic": false,
      "excluded": null
    },
    {
      "url": "https://whiskipedia.com/scotland/speyside/",
      "cluster_id": "c-distilleries",
      "coords": [
        0.55,
        0.38
      ],
      "risk": "overlap",
      "url_class": "normal",
      "variant_kind": null,
      "word_count": 783,
      "main_text_words": 763,
      "main_text_chars": 3815,
      "signature_words": 753,
      "signature_chars": 3765,
      "max_similarity": 0.916,
      "centroid_similarity": 0.826,
      "off_topic": false,
      "excluded": null
    },
    {
      "url": "https://whiskipedia.com/distilleries/ardbeg/",
      "cluster_id": "c-distilleries",
      "coords": [
        0.76,
        0.22
      ],
      "risk": "duplicate",
      "url_class": "normal",
      "variant_kind": null,
      "word_count": 354,
      "main_text_words": 334,
      "main_text_chars": 1670,
      "signature_words": 324,
      "signature_chars": 1620,
      "max_similarity": 0.898,
      "centroid_similarity": 0.798,
      "off_topic": false,
      "excluded": null
    },
    {
      "url": "https://whiskipedia.com/distilleries/lagavulin/",
      "cluster_id": "c-content",
      "coords": [
        0.2,
        -0.42
      ],
      "risk": "overlap",
      "url_class": "normal",
      "variant_kind": null,
      "word_count": 360,
      "main_text_words": 340,
      "main_text_chars": 1700,
      "signature_words": 330,
      "signature_chars": 1650,
      "max_similarity": 0.88,
      "centroid_similarity": 0.77,
      "off_topic": false,
      "excluded": null
    },
    {
      "url": "https://whiskipedia.com/blog/",
      "cluster_id": "c-content",
      "coords": [
        0.48,
        -0.62
      ],
      "risk": "thin content",
      "url_class": "normal",
      "variant_kind": null,
      "word_count": 132,
      "main_text_words": 112,
      "main_text_chars": 560,
      "signature_words": 102,
      "signature_chars": 510,
      "max_similarity": 0.862,
      "centroid_similarity": 0.742,
      "off_topic": false,
      "excluded": null
    },
    {
      "url": "https://whiskipedia.com/blog/peat-levels/",
      "cluster_id": null,
      "coords": [
        -0.72,
        -0.68
      ],
      "risk": "overlap",
      "url_class": "normal",
      "variant_kind": null,
      "word_count": 627,
      "main_text_words": 607,
      "main_text_chars": 3035,
      "signature_words": 597,
      "signature_chars": 2985,
      "max_similarity": 0.844,
      "centroid_similarity": 0.714,
      "off_topic": false,
      "excluded": null
    },
    {
      "url": "https://whiskipedia.com/search?q=islay",
      "cluster_id": null,
      "coords": [
        0.85,
        -0.55
      ],
      "risk": "overlap",
      "url_class": "parameterised",
      "variant_kind": null,
      "word_count": 231,
      "main_text_words": 211,
      "main_text_chars": 1055,
      "signature_words": 201,
      "signature_chars": 1005,
      "max_similarity": 0.826,
      "centroid_similarity": 0.686,
      "off_topic": true,
      "excluded": null
    },
    {
      "url": "https://whiskipedia.com/japan/",
      "cluster_id": "c-scotland",
      "coords": [
        -0.48,
        0.5
      ],
      "risk": "overlap",
      "url_class": "normal",
      "variant_kind": null,
      "word_count": 342,
      "main_text_words": 322,
      "main_text_chars": 1610,
      "signature_words": 312,
      "signature_chars": 1560,
      "max_similarity": 0.808,
      "centroid_similarity": 0.658,
      "off_topic": false,
      "excluded": null
    }
  ],
  "pairs": [
    {
      "url_a": "https://whiskipedia.com/scotland/",
      "url_b": "https://whiskipedia.com/scotland/islay/",
      "similarity": 0.96,
      "relation": "parent-child",
      "pair_class": null,
      "thin": false,
      "sim_percentile": 99
    },
    {
      "url_a": "https://whiskipedia.com/scotland/islay/",
      "url_b": "https://whiskipedia.com/scotland/speyside/",
      "similarity": 0.93,
      "relation": "parent-child",
      "pair_class": null,
      "thin": false,
      "sim_percentile": 98
    },
    {
      "url_a": "https://whiskipedia.com/distilleries/ardbeg/",
      "url_b": "https://whiskipedia.com/distilleries/lagavulin/",
      "similarity": 0.9,
      "relation": "sibling",
      "pair_class": null,
      "thin": false,
      "sim_percentile": 97
    },
    {
      "url_a": "https://whiskipedia.com/blog/",
      "url_b": "https://whiskipedia.com/blog/peat-levels/",
      "similarity": 0.87,
      "relation": "same-section",
      "pair_class": "time-sequenced",
      "thin": true,
      "sim_percentile": 96
    },
    {
      "url_a": "https://whiskipedia.com/scotland/",
      "url_b": "https://whiskipedia.com/japan/",
      "similarity": 0.84,
      "relation": "parent-child",
      "pair_class": null,
      "thin": false,
      "sim_percentile": 95
    }
  ],
  "clusters": [
    {
      "id": "c-scotland",
      "label": "/scotland \u00b7 whisky regions",
      "size": 4,
      "urls": [
        "https://whiskipedia.com/scotland/",
        "https://whiskipedia.com/scotland/islay/",
        "https://whiskipedia.com/scotland/speyside/",
        "https://whiskipedia.com/japan/"
      ],
      "relation": "parent-child",
      "thin": false,
      "time_sequenced": false,
      "suggested_canonical": "https://whiskipedia.com/scotland/"
    },
    {
      "id": "c-distilleries",
      "label": "/distilleries \u00b7 profile pages",
      "size": 2,
      "urls": [
        "https://whiskipedia.com/distilleries/ardbeg/",
        "https://whiskipedia.com/distilleries/lagavulin/"
      ],
      "relation": "sibling",
      "thin": false,
      "time_sequenced": false,
      "suggested_canonical": "https://whiskipedia.com/distilleries/ardbeg/"
    },
    {
      "id": "c-content",
      "label": "/blog \u00b7 explanatory content",
      "size": 2,
      "urls": [
        "https://whiskipedia.com/blog/",
        "https://whiskipedia.com/blog/peat-levels/"
      ],
      "relation": "same-section",
      "thin": true,
      "time_sequenced": true,
      "suggested_canonical": "https://whiskipedia.com/blog/peat-levels/"
    }
  ]
};
