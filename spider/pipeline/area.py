from spider.config.models import AreaExtractionConfig


# 自动地区提取统一收敛到省级行政区，地级市/自治州命中后会上卷到所属省份或直辖市。
AREA_DEFINITIONS = [
    {"name": "北京市", "aliases": ["北京市", "北京"]},
    {"name": "天津市", "aliases": ["天津市", "天津"]},
    {"name": "上海市", "aliases": ["上海市", "上海"]},
    {"name": "重庆市", "aliases": ["重庆市", "重庆"]},
    {"name": "河北省", "aliases": ["河北省", "河北", "石家庄", "唐山", "秦皇岛", "邯郸", "邢台", "保定", "张家口", "承德", "沧州", "廊坊", "衡水"]},
    {"name": "山西省", "aliases": ["山西省", "山西", "太原", "大同", "阳泉", "长治", "晋城", "朔州", "晋中", "运城", "忻州", "临汾", "吕梁"]},
    {"name": "辽宁省", "aliases": ["辽宁省", "辽宁", "沈阳", "大连", "鞍山", "抚顺", "本溪", "丹东", "锦州", "营口", "阜新", "辽阳", "盘锦", "铁岭", "朝阳", "葫芦岛"]},
    {"name": "吉林省", "aliases": ["吉林省", "吉林", "长春", "吉林市", "四平", "辽源", "通化", "白山", "松原", "白城", "延边"]},
    {"name": "黑龙江省", "aliases": ["黑龙江省", "黑龙江", "哈尔滨", "齐齐哈尔", "鸡西", "鹤岗", "双鸭山", "大庆", "伊春", "佳木斯", "七台河", "牡丹江", "黑河", "绥化", "大兴安岭"]},
    {"name": "江苏省", "aliases": ["江苏省", "江苏", "南京", "无锡", "徐州", "常州", "苏州", "南通", "连云港", "淮安", "盐城", "扬州", "镇江", "泰州", "宿迁"]},
    {"name": "浙江省", "aliases": ["浙江省", "浙江", "杭州", "宁波", "温州", "嘉兴", "湖州", "绍兴", "金华", "衢州", "舟山", "台州", "丽水"]},
    {"name": "安徽省", "aliases": ["安徽省", "安徽", "合肥", "芜湖", "蚌埠", "淮南", "马鞍山", "淮北", "铜陵", "安庆", "黄山", "滁州", "阜阳", "宿州", "六安", "亳州", "池州", "宣城"]},
    {"name": "福建省", "aliases": ["福建省", "福建", "福州", "厦门", "莆田", "三明", "泉州", "漳州", "南平", "龙岩", "宁德"]},
    {"name": "江西省", "aliases": ["江西省", "江西", "南昌", "景德镇", "萍乡", "九江", "新余", "鹰潭", "赣州", "吉安", "宜春", "抚州", "上饶"]},
    {"name": "山东省", "aliases": ["山东省", "山东", "济南", "青岛", "淄博", "枣庄", "东营", "烟台", "潍坊", "济宁", "泰安", "威海", "日照", "临沂", "德州", "聊城", "滨州", "菏泽"]},
    {"name": "河南省", "aliases": ["河南省", "河南", "郑州", "开封", "洛阳", "平顶山", "安阳", "鹤壁", "新乡", "焦作", "濮阳", "许昌", "漯河", "三门峡", "南阳", "商丘", "信阳", "周口", "驻马店", "济源"]},
    {"name": "湖北省", "aliases": ["湖北省", "湖北", "武汉", "黄石", "十堰", "宜昌", "襄阳", "鄂州", "荆门", "孝感", "荆州", "黄冈", "咸宁", "随州", "恩施", "仙桃", "潜江", "天门", "神农架"]},
    {"name": "湖南省", "aliases": ["湖南省", "湖南", "长沙", "株洲", "湘潭", "衡阳", "邵阳", "岳阳", "常德", "张家界", "益阳", "郴州", "永州", "怀化", "娄底", "湘西"]},
    {"name": "广东省", "aliases": ["广东省", "广东", "广州", "深圳", "珠海", "汕头", "佛山", "韶关", "湛江", "肇庆", "江门", "茂名", "惠州", "梅州", "汕尾", "河源", "阳江", "清远", "东莞", "中山", "潮州", "揭阳", "云浮"]},
    {"name": "海南省", "aliases": ["海南省", "海南", "海口", "三亚", "三沙", "儋州", "五指山", "琼海", "文昌", "万宁", "东方", "定安", "屯昌", "澄迈", "临高", "白沙", "昌江", "乐东", "陵水", "保亭", "琼中"]},
    {"name": "四川省", "aliases": ["四川省", "四川", "成都", "自贡", "攀枝花", "泸州", "德阳", "绵阳", "广元", "遂宁", "内江", "乐山", "南充", "眉山", "宜宾", "广安", "达州", "雅安", "巴中", "资阳", "阿坝", "甘孜", "凉山"]},
    {"name": "贵州省", "aliases": ["贵州省", "贵州", "贵阳", "六盘水", "遵义", "安顺", "毕节", "铜仁", "黔西南", "黔东南", "黔南"]},
    {"name": "云南省", "aliases": ["云南省", "云南", "昆明", "曲靖", "玉溪", "保山", "昭通", "丽江", "普洱", "临沧", "楚雄", "红河", "文山", "西双版纳", "大理", "德宏", "怒江", "迪庆"]},
    {"name": "陕西省", "aliases": ["陕西省", "陕西", "西安", "铜川", "宝鸡", "咸阳", "渭南", "延安", "汉中", "榆林", "安康", "商洛"]},
    {"name": "甘肃省", "aliases": ["甘肃省", "甘肃", "兰州", "嘉峪关", "金昌", "白银", "天水", "武威", "张掖", "平凉", "酒泉", "庆阳", "定西", "陇南", "临夏", "甘南"]},
    {"name": "青海省", "aliases": ["青海省", "青海", "西宁", "海东", "海北", "黄南", "海南州", "海南藏族自治州", "果洛", "玉树", "海西"]},
    {"name": "内蒙古自治区", "aliases": ["内蒙古自治区", "内蒙古", "呼和浩特", "包头", "乌海", "赤峰", "通辽", "鄂尔多斯", "呼伦贝尔", "巴彦淖尔", "乌兰察布", "兴安盟", "锡林郭勒", "阿拉善"]},
    {"name": "广西壮族自治区", "aliases": ["广西壮族自治区", "广西", "南宁", "柳州", "桂林", "梧州", "北海", "防城港", "钦州", "贵港", "玉林", "百色", "贺州", "河池", "来宾", "崇左"]},
    {"name": "西藏自治区", "aliases": ["西藏自治区", "西藏", "拉萨", "日喀则", "昌都", "林芝", "山南", "那曲", "阿里"]},
    {"name": "宁夏回族自治区", "aliases": ["宁夏回族自治区", "宁夏", "银川", "石嘴山", "吴忠", "固原", "中卫"]},
    {"name": "新疆维吾尔自治区", "aliases": ["新疆维吾尔自治区", "新疆", "乌鲁木齐", "克拉玛依", "吐鲁番", "哈密", "昌吉", "博尔塔拉", "巴音郭楞", "阿克苏", "克孜勒苏", "喀什", "和田", "伊犁", "塔城", "阿勒泰", "石河子", "阿拉尔", "图木舒克", "五家渠", "北屯", "铁门关", "双河", "可克达拉", "昆玉", "胡杨河", "新星"]},
    {"name": "香港特别行政区", "aliases": ["香港特别行政区", "香港"]},
    {"name": "澳门特别行政区", "aliases": ["澳门特别行政区", "澳门"]},
    {"name": "台湾省", "aliases": ["台湾省", "台湾", "台北", "新北", "桃园", "台中", "台南", "高雄", "基隆", "新竹", "嘉义", "苗栗", "彰化", "南投", "云林", "屏东", "宜兰", "花莲", "台东", "澎湖", "金门", "连江"]},
]


def _build_alias_lookup():
    # type: () -> dict
    lookup = {}
    for area in AREA_DEFINITIONS:
        standard_name = area["name"]
        for alias in area["aliases"]:
            lookup[alias] = standard_name
    return lookup


ALIAS_TO_STANDARD = _build_alias_lookup()


def _resolve_allowed_area_names(cfg):
    # type: (AreaExtractionConfig) -> set
    allowed = set()
    for keyword in cfg.province_keywords:
        keyword = str(keyword or "").strip()
        if keyword in ALIAS_TO_STANDARD:
            allowed.add(ALIAS_TO_STANDARD[keyword])

    if allowed:
        return allowed
    return set(area["name"] for area in AREA_DEFINITIONS)


def _build_matchers(cfg):
    # type: (AreaExtractionConfig) -> list
    allowed_names = _resolve_allowed_area_names(cfg)
    matchers = []
    for area in AREA_DEFINITIONS:
        if area["name"] not in allowed_names:
            continue
        for alias in area["aliases"]:
            matchers.append((alias, area["name"]))
    matchers.sort(key=lambda item: len(item[0]), reverse=True)
    return matchers


def _match_area_from_text(text, matchers):
    # type: (str, list) -> str
    text = str(text or "")
    for alias, standard_name in matchers:
        if alias in text:
            return standard_name
    return ""


def detect_area(title, content, cfg):
    # type: (str, str, AreaExtractionConfig) -> str
    # fixed_value 优先级最高，显式配置后直接返回，不再做自动归并。
    if cfg.fixed_value:
        return cfg.fixed_value.strip()

    if not cfg.enabled:
        return ""

    pools = [title, content] if cfg.use_title_first else [content, title]
    matchers = _build_matchers(cfg)
    for text in pools:
        area = _match_area_from_text(text, matchers)
        if area:
            return area

    if "全国" in (str(title or "") + str(content or "")):
        return "全国"
    return ""
