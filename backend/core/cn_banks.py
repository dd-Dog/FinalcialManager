"""常见中国境内银行名录（用于开户行选择与展示）。"""

CHINESE_BANK_CATALOG: list[dict[str, str]] = [
    {"code": "ICBC", "name": "中国工商银行"},
    {"code": "ABC", "name": "中国农业银行"},
    {"code": "BOC", "name": "中国银行"},
    {"code": "CCB", "name": "中国建设银行"},
    {"code": "COMM", "name": "交通银行"},
    {"code": "CMB", "name": "招商银行"},
    {"code": "SPDB", "name": "上海浦东发展银行"},
    {"code": "CIB", "name": "兴业银行"},
    {"code": "HXB", "name": "华夏银行"},
    {"code": "GDB", "name": "广发银行"},
    {"code": "PAB", "name": "平安银行"},
    {"code": "CITIC", "name": "中信银行"},
    {"code": "CEB", "name": "中国光大银行"},
    {"code": "CMBC", "name": "中国民生银行"},
    {"code": "CZB", "name": "浙商银行"},
    {"code": "BOS", "name": "上海银行"},
    {"code": "BOB", "name": "北京银行"},
    {"code": "NJCB", "name": "南京银行"},
    {"code": "NBCB", "name": "宁波银行"},
    {"code": "HZBANK", "name": "杭州银行"},
    {"code": "JSB", "name": "江苏银行"},
    {"code": "HSB", "name": "徽商银行"},
    {"code": "CQB", "name": "重庆银行"},
    {"code": "CDB", "name": "国家开发银行"},
    {"code": "ADBC", "name": "中国农业发展银行"},
    {"code": "EXIM", "name": "中国进出口银行"},
    {"code": "PSBC", "name": "中国邮政储蓄银行"},
    {"code": "HSBC_CN", "name": "汇丰银行（中国）"},
    {"code": "CITI_CN", "name": "花旗银行（中国）"},
    {"code": "SCB_CN", "name": "渣打银行（中国）"},
    {"code": "BEA_CN", "name": "东亚银行（中国）"},
    {"code": "RCC", "name": "农村商业银行（农商行）"},
    {"code": "RCCU", "name": "农村信用社"},
    {"code": "VCB", "name": "村镇银行"},
    {"code": "OTHER", "name": "其他银行（名称见账户名）"},
]


def filter_banks(query: str) -> list[dict[str, str]]:
    q = (query or "").strip().lower()
    if not q:
        return list(CHINESE_BANK_CATALOG)
    return [
        b
        for b in CHINESE_BANK_CATALOG
        if q in b["name"].lower() or q in b["code"].lower()
    ]
