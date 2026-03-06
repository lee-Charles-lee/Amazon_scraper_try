import csv
import os
import random
import re
import gc
import time
from datetime import datetime
from urllib.parse import quote_plus
from bs4 import BeautifulSoup
from DrissionPage import ChromiumOptions, ChromiumPage
try:
    from DrissionPage.errors import PageDisconnectedError
except Exception:
    PageDisconnectedError = None



DEFAULT_UA = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36 Edg/144.0.0.0'

)

class AmazonScraper:
    """亚马逊评论采集器"""

    def __init__(self, 
                 headless=False, 
                 user_agent=DEFAULT_UA, 
                 logger=None,
                 keyword = 'niimbot b21 pro',
                 max_list_pages=2,
                 max_products_per_page=2,
                 max_review_pages=2):
        """
        初始化浏览器
        :param headless: 是否无头模式
        """
        self.keyword = keyword  # 搜索关键词
        self.max_list_pages = max(1,min(max_list_pages, 20))  # 限制列表页最大值
        self.max_products_per_page = max(1,min(max_products_per_page, 20)) # 限制每页产品数量最大值
        self.max_review_pages = max(1,min(max_review_pages, 10)) # 限制评论页最大值

        co = ChromiumOptions()
        co.set_argument('--inprivate')
        co.headless(headless)  # 是否无头模式
        self.user_agent = user_agent
        co.set_user_agent(self.user_agent)
    
        edge_path = r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
        co.set_browser_path(edge_path)
    
        self._options = co
        self._logger = logger

        self.page = self._create_page()
        self.page.timeouts.base = 5

        self.temp_data = {
            'asin':[],
            'product_links':[],
            'review_links': [],
            'asin_review_map': {},
            'all_reviews': []

        }

    # --- Browser lifecycle ---

    def _create_page(self):
        try:
            return ChromiumPage(addr_or_opts=self._options)
        except TypeError:
            return ChromiumPage(addr_driver_opts=self._options)

    def _reset_page(self):
        self.cleanup_temp_data()
        try:
            self.page.quit()
        except Exception as e:
            self._log(f'关闭页面时出错: {e}')
            pass

        self.page = self._create_page()
        self.page.timeouts.base = 5

    def _log(self, message):
        if self._logger:
            self._logger(message)
            return
        print(message)  

    def _safe_get(self, url, retry=2):
        for attempt in range(1, retry + 1):
            try:
                self.page.get(url)
                return True
            except Exception as e:
                if PageDisconnectedError and isinstance(e, PageDisconnectedError):
                    self._log(f'    页面断开，重试 {attempt}/{retry}...')
                    self._reset_page()
                    time.sleep(2)
                    continue
                if e.__class__.__name__ == 'PageDisconnectedError':
                    self._log(f'    页面断开，重试 {attempt}/{retry}...')
                    self._reset_page()
                    time.sleep(2)
                    continue
                self._log(f'    打开页面失败: {url} -> {e}')
                return False
        return False
    
    #清理临时数据
    def cleanup_temp_data(self):
        self._log('正在清理临时数据...')
        try:
            self.temp_data['asins'].clear()
            self.temp_data['product_links'].clear()
            self.temp_data['asin_review_map'].clear()
            self.temp_data['all_reviews'].clear()

            gc.collect()
            self._log('临时数据清理完成')
        except Exception as e:
            self._log('清理失败{e}')

    #清理浏览器数据
    def cleanup_browser(self):
        self._log('正在清理浏览器数据...')
        try:
            self.cleanup_temp_data()
            if hasattr(self,'page') and self.page:
                self.page.stop_loading()
                self.page.quit()
                self.page = None

            gc.collect()
            self._log('浏览器资源清理完成')
        except Exception as e:
            self._log(' 清理浏览器资源失败：{e}') 

    #清理文件句柄
    def cleanup_file_handles(self, file_path=None):
        if file_path and os.path.exists(file_path):
            try:
                # 重置文件权限（Windows下防止文件锁定）
                os.chmod(file_path, 0o777)
                self._log(f'文件句柄清理完成: {file_path}')
            except Exception as e:
                self._log(f'清理文件句柄失败: {e}')
        

    
    #打开亚马逊网页，自己登录
    def open_amazon_homepage(self):
        homepage_url = 'https://www.amazon.com/'
        if not self._safe_get(homepage_url):
            return False
        self._log('请在浏览器中登录亚马逊账户...')
        self._log('登陆完成后，请按回车继续')
        input()

        self._log('正在验证登录状态...')
        time.sleep(2)  # 给页面一点加载时间
        if self.page.ele('//span[contains(text(), "Account & Lists")]', timeout=3) or \
            self.page.ele('//span[contains(text(), "Hello,")]', timeout=3):
            self._log('登录验证成功！开始爬取数据...')
        else:
            self._log('登录验证失败，可能需要重新登录！')
           
    
        return True
    
    #输入搜索词并得到搜索结果页面
    def _search_product(self):
        self._log(f'正在搜索产品: {self.keyword}')
        search_url = f'https://www.amazon.com/s?k={quote_plus(self.keyword)}'
        if not self._safe_get(search_url):
            return False
        time.sleep(random.uniform(3, 4))  # 等待页面加载
        return True
    
    #获取搜索结果中产品的asin
    def _get_product_asins(self):
        self._log('正在获取产品ASIN...')
        asins = set()
        current_page = 1
        total_valid_products = 0

        while True:
            soup = BeautifulSoup(self.page.html, 'html.parser')
            valid_divs = soup.select('div[role="listitem"][data-asin]:not([style*="display: none"])')

            page_valid_asins = []
            for div in valid_divs:
                link = div.select_one('a[href *="/dp/"]')
                if not link:
                    continue

                asin = div.get('data-asin', '').strip()
                if  not asin:
                    continue

                page_valid_asins.append(asin)

            if not page_valid_asins or current_page > self.max_list_pages:
                break
            
            total_valid_products += len(page_valid_asins[:self.max_products_per_page])
            asins.update(page_valid_asins[:self.max_products_per_page])    # 只保留每页前M个有效ASIN  

            if not self._has_next_list_page():
                break
            self.page.eles("li.s-list-item-margin-right-adjustment a")[-1].click()
            time.sleep(random.uniform(3, 4))  
            current_page += 1

        self._log(f'共获取到 {len(asins)} 个唯一有效ASIN,总计 {total_valid_products} 个商品条目')   
        final_asins = list(asins)
        self.temp_data['asins'] = final_asins
        return final_asins
    
       

    
    #判断是否有下一页搜索结果
    def _has_next_list_page(self):
        self._log('正在检查是否有下一页搜索结果...')
        try:
            all_next_btns = self.page.eles('li.s-list-item-margin-right-adjustment a')  

            if not all_next_btns:
                return False
            
            next_button = all_next_btns[-1]

            if not next_button:
                return False
            if next_button.get_attribute('class'):
                return False
            return True
        except Exception as e:
            self._log(f'    检查下一页失败: {e}')
            return False
    
    #将asins列表里面的asin拼接成产品链接
    def _get_product_links(self, asins):
        self._log('正在生成产品链接...')
        links = []
        for asin in asins:
            link = f'https://www.amazon.com/dp/{asin}'
            links.append(link)
        self.temp_data['product_links'] = links
        return links
    
    #打开links列表里面的链接，获取查看全部评论的链接
    def _get_all_review_links(self, links):
        self._log('正在获取查看全部评论的链接...')
        all_review_links = []
        for link in links:
            if not self._safe_get(link):
                continue
            time.sleep(random.uniform(3, 4))  # 等待页面加载
            soup = BeautifulSoup(self.page.html, 'html.parser')
            all_review_link = soup.select_one('a[data-hook="see-all-reviews-link-foot"]')
            if all_review_link:
                all_review_links.append('https://www.amazon.com' + all_review_link['href'])
        self.temp_data['review_links'] = all_review_links
        return all_review_links  
    
    ######对应asin和查看全部评论的链接#
    def _map_asin_to_review_link(self, asins, all_review_links):
        self._log('正在将ASIN与评论链接进行映射...')
        asin_review_map = {}

        for asin in asins:
            all_review_link = None 

            for review_link in all_review_links:
                if asin in review_link:
                    all_review_link = review_link
                    break
            
            if all_review_link:
                asin_review_map[asin] = all_review_link

        self.temp_data['asin_review_map'] = asin_review_map.copy()
        return asin_review_map
    
    #根据asin，通过点击下一页，抓取对应的总评论链接下的评论数据防止被反爬机制识别为批量请求
    def _scrape_reviews_for_asin(self, asin, review_link):
        self._log(f'正在抓取 {asin} 的评论...')
        reviews = []
        page_num = 1

        if not self._safe_get(review_link):
            self._log(f'    无法打开评论链接: {review_link}')
            return reviews
        time.sleep(random.uniform(3, 4))  
        
        while page_num <= self.max_review_pages:
            self._log(f'正在打开第{page_num}页评论...')

            self._log(f'正在找查看更多的按钮')
            more_buttons = self.page.eles('a[data-hook="redirect-see-more"]')
            for button in more_buttons:
                try:
                    button.click()
                    time.sleep(random.uniform(1, 2))
                except Exception as e:
                    self._log(f'    点击查看更多按钮失败: {e}')
                    pass

            soup = BeautifulSoup(self.page.html,'html.parser')
            
            review_divs = soup.select(
                'div[data-hook="mobile_review-content"],'
                'li[data-hook="review"],'
                'div[data-hook="revie"]'
            )

   
            self._log(f'第{page_num}页,找到 {len(review_divs)} 条评论，正在提取数据...')

            for div in review_divs:
                review = self._extract_review_data(div)
                if review:
                    review['asin'] = asin  #字典的赋值
                    
                    reviews.append(review)

            if self._has_review_next_page():
                try:
                    self._log(f'正在点击下一页评论...')
                    pre_url = self.page.url
                    next_li = self.page.ele('css:.a-pagination .a-last',timeout=1)
                    next_btn = next_li.ele('css:a', timeout=1)
                    next_btn.click()
                    time.sleep(random.uniform(4, 5))
                    try:
                        self.page.wait.url_change(pre_url,exclude=True,timeout=5)
                    except Exception as e:
                        self._log(f'    等待页面跳转失败: {e},继续等待...')
                   
                    page_num += 1
                    self._log(f'成功进入第{page_num}页评论')
                except Exception as e:
                    self._log(f'    点击下一页失败: {e},已爬取{page_num}页评论')
                    break
            else:
                    self._log(f'    没有下一页评论了，已爬取{page_num}页评论')
                    break

        return reviews #返回多条评论信息
    
    #判断是否有下一页评论
    def _has_review_next_page(self):
        self._log('正在检查是否有下一页评论...')
        try:
            next_li = self.page.ele('css:.a-pagination .a-last', timeout=1)

            if not next_li:
                self._log('未找到下一页评论的li元素')
                return False
        
            if 'a-disabled' in (next_li.attr('class') or ''):
                self._log('下一页评论按钮不可点击')
                return False
        
            next_btn = next_li.ele('css:a', timeout=1)
            if not next_btn:
                self._log('未找到下一页评论的a元素')
                return False
        
            return True
    
        except Exception as e:
            self._log(f'    检查下一页评论失败: {e}')
            return False
                
    #从评论页面提取评论数据
    def _extract_review_data(self, review_div):
        self._log('正在提取评论数据...')
        try:
            review_id = review_div.get('id', '').strip() #.get()方法获取id属性，如果没有则返回空字符串，并去除两端的空白字符
            
            emoji_pattern = re.compile(
                "["
                u"\U0001F600-\U0001F64F"  # 表情符号
                u"\U0001F300-\U0001F5FF"  # 符号/图标
                u"\U0001F680-\U0001F6FF"  # 交通/地图
                u"\U0001F1E0-\U0001F1FF"  # 国旗
                u"\U00002500-\U00002BEF"  # 各种符号
                "]+",
                re.UNICODE
            )

            title = self._bs_select_text(
                review_div,
                selectors = [
                    'a[data-hook="review-title"] span.cr-original-review-content',
                    'a[data-hook="review-title"]'
                ]
            )
            if title:
                if 'stars' in title:
                    title = title.split('stars')[1].strip()
                elif 'STARS' in title:
                    title = title.split('STARS')[1].strip()
                else:
                    title = '11'

            rating_ele = review_div.select_one('i[data-hook="review-star-rating"] span')
            if rating_ele:
                raw_rating = rating_ele.get_text(strip=True)
                rating = self.normalize_text(raw_rating)
                parts = rating.split(' ')
                rating = parts[0] if parts else ''  
            else:
                rating = ''

            author_ele = review_div.select_one('span.a-profile-name')
            if author_ele:
                raw_author = author_ele.get_text(strip=True)
                author = self.normalize_text(raw_author)
            else:
                author = ''

            content_ele = review_div.select_one('span[data-hook="review-body"] span')
            if content_ele:
                raw_content = content_ele.get_text(strip=True)
                content = self.normalize_text(raw_content)
            else:
                content = ''
            content = emoji_pattern.sub(r'', content)

            data_site_element = review_div.select_one('span[data-hook="review-date"]')
            site = ''
            date = ''
            raw_data_str = ''

            if data_site_element:
                data_site_text = data_site_element.get_text(strip=True)
                if 'Reviewed in the ' in data_site_text and ' on ' in data_site_text:
                    site_part = data_site_text.split('Reviewed in the ')[1]
                    site = site_part.split(' on ')[0].strip()
                    raw_data_str = data_site_text.split('on ')[1].strip()
                else:
                    date = ''
                    site = ''
            else:
                site = ''
                date = ''

           #统一时间格式为YYYY/MM/DD
            if raw_data_str:
                try:
                    date_obj = datetime.strptime(raw_data_str, '%B %d, %Y')
                    date = date_obj.strftime('%Y/%m/%d')
                except ValueError:
                    date = raw_data_str

            self._log(f'提取到评论: {review_id} - {title} - {rating} - {author} - {date} - {site}')
            return {
                'review_id': review_id,
                'title': title,
                'rating': rating,
                'author': author,
                'content': content,
                'date': date,
                'site': site
                } #返回单条评论信息
        except Exception as e:
            self._log(f'    提取评论数据失败: {e}')
            return None
        
    #文本规范化处理
    def normalize_text(self, text):
        if not text:
            return ''
        text = text.replace('’',"'").replace('‘',"'").replace('“','"').replace('”','"')  # 替换常见的引号变体,防止出现编码问题导致的引号无法识别
        text = re.sub(r'\s+', ' ', text)  # 将多个空白字符替换为一个空格
        return text.strip()  # 去除文本两端的空白字符
    
    #按顺序尝试多个CSS选择器提取评论文本，适配不同页面结构，保证爬虫稳定运行
    def _bs_select_text(self, soup, selectors):
        if isinstance(selectors, str):
            selectors = [selectors]
        for selector in selectors:
            try:
                ele = soup.select_one(selector)
                if ele:
                    text = self.normalize_text(ele.get_text())
                    if text:
                        return text
            except:
                continue
        return ''    

  
    '''
    #根据多个选择器获取文本内容，适应不同页面结构
    def _normalize_text_by_selectors(self, soup, selectors):
        for selector in selectors:
            element = soup.select_one(selector)
            if element:
                return self.normalize_text(element.get_text(strip=True))
        return ''
    '''

    #保存评论数据到csv文件
    def _save_reviews_to_csv(self, reviews, filename):
        if not reviews:
            self._log('没有评论数据可保存')
            return
        
        try:
            desktop_path = os.path.join(os.path.expanduser('~'), 'Desktop')
            safe_keyword = self.keyword.replace(' ', '_').replace('/', '_').replace('\\', '_')
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f'{safe_keyword}_reviews_{timestamp}.csv'
            save_path = os.path.join(desktop_path, filename)

            headers = reviews[0].keys() if reviews else []

            with open(save_path, mode='w', newline='', encoding='utf-8-sig') as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=headers)
                writer.writeheader()
                writer.writerows(reviews)

            self._log(f'评论数据已保存到 {save_path}')

        except Exception as e:
            self._log(f'    保存评论数据失败: {e}')
            



        self._log(f'正在保存评论数据到 {filename}...')
        fieldnames = ['asin', 'review_id', 'title', 'rating', 'author', 'content', 'date', 'site']
        try:
            with open(filename, mode='w', newline='', encoding='utf-8') as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()
                for review in reviews:
                    writer.writerow(review)
            self._log(f'评论数据已保存到 {filename}')
            print("当前工作目录：" + os.getcwd())
        except Exception as e:
            self._log(f'    保存评论数据失败: {e}11111')

        self.cleanup_file_handles(save_path)
        self._log(f'评论数据已保存到 {save_path}')

    #运行爬虫
    def run(self):
        try:
            if not self.open_amazon_homepage():
                self._log('无法打开亚马逊主页，爬虫终止。')
                return

            if not self._search_product():
                self._log('搜索产品失败，爬虫终止。')
                return

            asins = self._get_product_asins()
            if not asins:
                self._log('未找到任何产品，爬虫终止。')
                return

            product_links = self._get_product_links(asins)
            all_review_links = self._get_all_review_links(product_links)
            asin_review_map = self._map_asin_to_review_link(asins, all_review_links)

            all_reviews = []
            for asin, review_link in asin_review_map.items():
                reviews = self._scrape_reviews_for_asin(asin, review_link)
                all_reviews.extend(reviews)

            if all_reviews:
                filename = f'{self.keyword}_reviews.csv'
                self._save_reviews_to_csv(all_reviews, filename)
            else:
                self._log('未抓取到任何评论数据。')
                self.clean_temp_data()
        except Exception as e:
            self._log(f'爬虫运行异常: {e}')
            self.cleanup_browser()
        finally:
            self.cleanup_browser

if __name__ == "__main__":
    scraper = AmazonScraper(
        headless=False, 
        user_agent=DEFAULT_UA, 
        keyword='niimbot b21 pro',
        max_list_pages=2,
        max_products_per_page=2,
        max_review_pages=2
    )
    try:
        scraper.run()
    except KeyboardInterrupt as e:
        scraper._log(f'爬虫执行出错: {e}')
        scraper.cleanup_browser()
    except Exception as e:   # 新增
        scraper._log(f'爬虫执行出错: {e}')
        scraper.cleanup_browser()

    
 
